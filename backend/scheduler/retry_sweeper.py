"""Periodically moves due entries from the delayed-retry ZSET back onto the
main task stream, so a task that failed and was scheduled for retry
(Step 10 Part 2/3) actually gets re-attempted instead of waiting forever.

This closes a gap that was deliberately deferred, then discovered for real
during Step 11 manual verification: a task that timed out on its first
attempt correctly computed a backoff delay and wrote it to retry:pending,
but nothing ever read that ZSET back out. This is the piece that reads it.
"""

import asyncio
import logging
import time

from app.queue.retry_queue import RetryQueue
from app.queue.stream_client import StreamQueue

logger = logging.getLogger("scheduler.retry_sweeper")

DEFAULT_SWEEP_INTERVAL_SECONDS = 2
DEFAULT_BATCH_SIZE = 100


class RetrySweeper:
    def __init__(
        self,
        retry_queue: RetryQueue,
        stream_queue: StreamQueue,
        *,
        interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.retry_queue = retry_queue
        self.stream_queue = stream_queue
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size

    async def sweep_once(self) -> int:
        """Move every currently-due entry back onto the stream. Returns how
        many were successfully moved. A single pass, not a loop -- callers
        (the background loop, or a test) control the looping."""
        due_task_ids = await self.retry_queue.pop_due(time.time(), limit=self.batch_size)

        enqueued_count = 0
        for task_id in due_task_ids:
            try:
                await self.stream_queue.enqueue(task_id)
                enqueued_count += 1
            except Exception:
                # pop_due already removed this from retry:pending -- without
                # this, a transient enqueue failure would silently lose the
                # task rather than just delay it. Reschedule for immediate
                # retry (score = now) so the next sweep picks it back up.
                logger.exception(
                    "Failed to re-enqueue task %s after popping it from retry:pending; "
                    "rescheduling for the next sweep rather than losing it.",
                    task_id,
                )
                await self.retry_queue.schedule_retry(task_id, time.time())

        if enqueued_count:
            logger.info("Re-enqueued %d retry-pending task(s).", enqueued_count)
        return enqueued_count

    async def run_forever(self, shutdown_event: asyncio.Event) -> None:
        logger.info("Retry sweeper started (interval=%.1fs).", self.interval_seconds)
        while not shutdown_event.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Retry sweep failed; will retry on the next interval.")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass  # normal case: the interval elapsed, loop again
        logger.info("Retry sweeper stopped.")