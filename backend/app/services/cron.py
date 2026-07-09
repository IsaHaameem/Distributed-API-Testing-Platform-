"""Shared cron-expression next-occurrence computation, used by both
ScheduleService (computing next_run_at when a schedule is created/updated)
and the scheduler's CronScheduler (recomputing it after each trigger).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter


def compute_next_run_at(cron_expression: str, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    return croniter(cron_expression, now).get_next(datetime)