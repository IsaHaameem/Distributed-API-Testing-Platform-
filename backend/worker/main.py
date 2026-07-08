"""Worker process entrypoint. Registers with the platform, then runs a
heartbeat loop and a stream-consumer loop concurrently until told to shut
down, at which point in-flight work finishes, the worker deregisters, and
the process exits cleanly.

Run directly: python -m worker.main
"""

import asyncio
import logging
import os
import signal
import socket
import uuid

import httpx

from app.config import get_settings
from app.core.logging_config import setup_logging
from app.core.redis_client import get_redis_client
from app.database import AsyncSessionFactory, engine
from app.queue.constants import TASK_STREAM_NAME, WORKER_CONSUMER_GROUP
from app.queue.retry_queue import RetryQueue
from app.queue.run_context import RunContext
from app.queue.stream_client import StreamEntry, StreamQueue
from app.queue.worker_registry import WorkerRegistry
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.assertion_repository import AssertionRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.worker_service import WorkerService
from worker.executor import Executor
from worker.result_writer import ResultWriter, TaskOutcome
from worker.task_processor import TaskProcessingError, TaskProcessor

logger = logging.getLogger("worker.main")

settings = get_settings()


class WorkerProcess:
    def __init__(
        self,
        *,
        stream_name: str = TASK_STREAM_NAME,
        consumer_group: str = WORKER_CONSUMER_GROUP,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.worker_id = None
        self.consumer_name = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.active_tasks_count = 0
        self.shutdown_event = asyncio.Event()

        self.redis_client = get_redis_client()
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient()

        self.stream_queue = StreamQueue(self.redis_client, stream_name, consumer_group)
        self.run_context = RunContext(self.redis_client)
        self.retry_queue = RetryQueue(self.redis_client)
        self.executor = Executor(self.http_client)
        self.result_writer = ResultWriter()

    async def start(self) -> None:
        await self.stream_queue.ensure_group()
        await self._register()

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._heartbeat_loop())
                tg.create_task(self._consume_loop())
        finally:
            await self._deregister()
            if self._owns_http_client:
                await self.http_client.aclose()
            await self.redis_client.aclose()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested; finishing in-flight work before exiting.")
        self.shutdown_event.set()

    async def _register(self) -> None:
        async with AsyncSessionFactory() as session:
            worker_service = WorkerService(WorkerRepository(session), WorkerRegistry(self.redis_client))
            worker = await worker_service.register(
                hostname=socket.gethostname(), pid=os.getpid(), capacity=settings.worker_capacity
            )
            await session.commit()
            self.worker_id = worker.id

        logger.info(
            "Worker %s registered (consumer=%s, capacity=%d)",
            self.worker_id,
            self.consumer_name,
            settings.worker_capacity,
        )

    async def _deregister(self) -> None:
        if self.worker_id is None:
            return
        async with AsyncSessionFactory() as session:
            worker_service = WorkerService(WorkerRepository(session), WorkerRegistry(self.redis_client))
            await worker_service.deregister(worker_id=self.worker_id)
            await session.commit()
        logger.info("Worker %s deregistered.", self.worker_id)

    async def _heartbeat_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                async with AsyncSessionFactory() as session:
                    worker_service = WorkerService(
                        WorkerRepository(session), WorkerRegistry(self.redis_client)
                    )
                    await worker_service.heartbeat(
                        worker_id=self.worker_id, active_tasks_count=self.active_tasks_count
                    )
                    await session.commit()
            except Exception:
                logger.exception("Heartbeat failed; will retry on the next interval.")

            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(), timeout=settings.worker_heartbeat_interval_seconds
                )
            except TimeoutError:
                pass  # normal case: the interval elapsed, loop again

    async def _consume_loop(self) -> None:
        while not self.shutdown_event.is_set():
            entries = await self.stream_queue.consume(
                self.consumer_name, count=settings.worker_capacity, block_ms=2000
            )
            if not entries:
                continue

            logger.info(
                "Consumed %d task(s) as %s: %s",
                len(entries),
                self.consumer_name,
                [str(e.task_id) for e in entries],
            )

            self.active_tasks_count = len(entries)
            results = await asyncio.gather(
                *(self._process_entry(entry) for entry in entries), return_exceptions=True
            )
            self.active_tasks_count = 0

            entry_ids_to_ack: list[str] = []
            outcomes: list[TaskOutcome] = []
            for entry, result in zip(entries, results):
                if isinstance(result, BaseException):
                    logger.error(
                        "Unexpected error processing task %s; leaving unacknowledged.",
                        entry.task_id,
                        exc_info=result,
                    )
                    continue
                entry_id, outcome = result
                entry_ids_to_ack.append(entry_id)
                if outcome is not None:
                    outcomes.append(outcome)

            if outcomes:
                async with AsyncSessionFactory() as session:
                    await self.result_writer.write_batch(outcomes, session)
                logger.info(
                    "Wrote batch of %d outcome(s): %s",
                    len(outcomes),
                    [(str(o.test_task_id), o.new_status.value) for o in outcomes],
                )

            # Ack only after the batch is durably written. If the ack itself
            # fails, the entry gets reclaimed and reprocessed later -- a
            # harmless extra attempt -- rather than a written result
            # silently never being acknowledged.
            if entry_ids_to_ack:
                await self.stream_queue.ack(*entry_ids_to_ack)
                logger.info("Acknowledged %d entry/entries.", len(entry_ids_to_ack))

    async def _process_entry(self, entry: StreamEntry) -> tuple[str, TaskOutcome | None]:
        async with AsyncSessionFactory() as session:
            processor = TaskProcessor(
                TestTaskRepository(session),
                TestRunRepository(session),
                ApiRequestRepository(session),
                AssertionRepository(session),
                self.executor,
                self.run_context,
                self.retry_queue,
            )
            try:
                outcome = await processor.process_task(entry.task_id, self.worker_id)
                logger.info("Task %s processed: %s", entry.task_id, outcome.new_status.value)
                return entry.entry_id, outcome
            except TaskProcessingError:
                logger.warning(
                    "Task %s references data that no longer exists; acknowledging so it "
                    "doesn't retry forever against an unrecoverable state.",
                    entry.task_id,
                )
                return entry.entry_id, None


async def main() -> None:
    setup_logging(settings.log_level)
    process = WorkerProcess()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, process.request_shutdown)

    try:
        await process.start()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())