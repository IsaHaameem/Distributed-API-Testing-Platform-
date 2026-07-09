"""Periodically checks for schedules whose next_run_at has passed and
triggers a run for each -- the cron-triggered counterpart to Part 1's retry
sweep. Runs inside the same backend process, alongside the retry sweeper,
both started from app.main's lifespan.
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.core.exceptions import CollectionHasNoRequestsError
from app.database import AsyncSessionFactory
from app.queue.stream_client import StreamQueue
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.environment_variable_repository import EnvironmentVariableRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.request_result_repository import RequestResultRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
from app.services.cron import compute_next_run_at
from app.services.test_run_service import TestRunService

logger = logging.getLogger("scheduler.cron_scheduler")

DEFAULT_CRON_CHECK_INTERVAL_SECONDS = 30
DEFAULT_BATCH_SIZE = 50


class CronScheduler:
    def __init__(
        self,
        stream_queue: StreamQueue,
        *,
        interval_seconds: float = DEFAULT_CRON_CHECK_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.stream_queue = stream_queue
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size

    async def sweep_once(self) -> int:
        """Trigger a run for every currently-due, active schedule. Returns
        how many runs were successfully triggered. A single pass, not a
        loop -- callers (the background loop, or a test) control looping."""
        async with AsyncSessionFactory() as session:
            schedule_repository = ScheduleRepository(session)
            due_schedules = await schedule_repository.list_due(
                datetime.now(timezone.utc), limit=self.batch_size
            )
            if not due_schedules:
                return 0

            test_run_service = TestRunService(
                TestRunRepository(session),
                TestTaskRepository(session),
                ApiRequestRepository(session),
                EnvironmentVariableRepository(session),
                CollectionRepository(session),
                ProjectRepository(session),
                OrganizationMemberRepository(session),
                self.stream_queue,
                RequestResultRepository(session),
            )

            triggered_count = 0
            for schedule in due_schedules:
                try:
                    await test_run_service.create_scheduled_run(
                        collection_id=schedule.collection_id, initiated_by=schedule.created_by
                    )
                    triggered_count += 1
                except CollectionHasNoRequestsError:
                    logger.warning(
                        "Schedule %s is due but its collection has no requests; skipping "
                        "this cycle.",
                        schedule.id,
                    )
                except Exception:
                    logger.exception("Failed to trigger scheduled run for schedule %s.", schedule.id)

                # Advance next_run_at regardless of whether triggering
                # succeeded -- a schedule that errors every cycle should
                # wait for its next real cron occurrence, not be retried
                # every single sweep interval forever.
                next_run_at = compute_next_run_at(schedule.cron_expression, schedule.timezone)
                await schedule_repository.update(
                    schedule, last_run_at=datetime.now(timezone.utc), next_run_at=next_run_at
                )

            await session.commit()

        if triggered_count:
            logger.info("Triggered %d scheduled run(s).", triggered_count)
        return triggered_count

    async def run_forever(self, shutdown_event: asyncio.Event) -> None:
        logger.info("Cron scheduler started (interval=%.1fs).", self.interval_seconds)
        while not shutdown_event.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Cron sweep failed; will retry on the next interval.")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass  # normal case: the interval elapsed, loop again
        logger.info("Cron scheduler stopped.")