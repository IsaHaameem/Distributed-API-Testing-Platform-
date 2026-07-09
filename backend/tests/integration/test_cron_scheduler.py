"""Integration tests for the cron-trigger sweep -- the piece that reads
schedules.next_run_at and creates a real test_run when a schedule is due.

Uses an isolated, unique-per-test stream (same reasoning as
test_retry_sweeper.py and test_run_orchestration.py): the real backend
process runs a live CronScheduler continuously, and these tests must never
share the real production stream with it.

_cleanup_schedules (autouse) deletes every schedule this file creates at
the end of each test, pass or fail. Without it, schedules accumulate
across every run of this file forever -- and since list_due() correctly
scans the whole table (that's its actual job in production), a stray
schedule from a much earlier run can make a completely unrelated test's
sweep_once() call return far more than the one schedule it created. For
the same reason, assertions here check outcomes scoped to each test's own
collection_id rather than a raw global count -- "how many schedules exist
somewhere in a shared database" was never a safe thing for a single test to
assert on.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.database import AsyncSessionFactory
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.models.enums import HttpMethod, OrganizationRole, TestRunType
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.schedule import Schedule
from app.models.test_run import TestRun
from app.models.user import User
from app.queue.stream_client import StreamQueue
from scheduler.cron_scheduler import CronScheduler

_created_schedule_ids: list[uuid.UUID] = []


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_schedules():
    """Delete every schedule created via _build_schedule during this test,
    regardless of pass/fail. Uses its own session, separate from db_session,
    since it must run at teardown after the test's own session may already
    be in whatever state the test left it in."""
    _created_schedule_ids.clear()
    yield
    if _created_schedule_ids:
        async with AsyncSessionFactory() as session:
            await session.execute(delete(Schedule).where(Schedule.id.in_(_created_schedule_ids)))
            await session.commit()


def _isolated_stream(redis_client: Redis) -> StreamQueue:
    suffix = uuid.uuid4().hex[:12]
    return StreamQueue(redis_client, f"test:cron:stream:{suffix}", f"test:cron:group:{suffix}")


async def _build_schedule(
    db_session: AsyncSession,
    *,
    cron_expression: str = "* * * * *",
    is_active: bool = True,
    next_run_at: datetime | None = None,
    request_count: int = 1,
) -> dict:
    user = User(
        email=f"cron-test-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("a-strong-password-123"),
        full_name="Cron Test User",
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(name="Cron Test Org", slug=f"cron-test-{uuid.uuid4().hex[:12]}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))

    project = Project(organization_id=org.id, name="Project", created_by=user.id)
    db_session.add(project)
    await db_session.flush()

    collection = Collection(project_id=project.id, name="Collection")
    db_session.add(collection)
    await db_session.flush()

    for i in range(request_count):
        db_session.add(
            ApiRequest(
                collection_id=collection.id,
                name=f"Request {i}",
                method=HttpMethod.GET,
                url="https://example.com",
            )
        )
    await db_session.flush()

    schedule = Schedule(
        collection_id=collection.id,
        cron_expression=cron_expression,
        timezone="UTC",
        is_active=is_active,
        next_run_at=(
            next_run_at if next_run_at is not None else datetime.now(timezone.utc) - timedelta(seconds=1)
        ),
        created_by=user.id,
    )
    db_session.add(schedule)
    await db_session.commit()

    _created_schedule_ids.append(schedule.id)

    return {"user": user, "collection": collection, "schedule": schedule}


@pytest.mark.asyncio
async def test_sweep_once_triggers_a_due_active_schedule(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    ctx = await _build_schedule(db_session)
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    triggered = await scheduler.sweep_once()

    # >=1, not ==1: list_due() correctly scans the whole schedules table --
    # other genuinely-due schedules elsewhere are not this test's concern.
    # Whether OUR schedule specifically was triggered is what the run
    # lookup below actually confirms.
    assert triggered >= 1

    run = (
        await db_session.execute(select(TestRun).where(TestRun.collection_id == ctx["collection"].id))
    ).scalar_one()
    assert run.run_type == TestRunType.SCHEDULED
    assert run.initiated_by == ctx["user"].id
    assert run.total_tasks == 1

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_sweep_once_skips_inactive_schedule(db_session: AsyncSession, redis_client: Redis) -> None:
    ctx = await _build_schedule(db_session, is_active=False)
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    await scheduler.sweep_once()  # not asserting the global count -- other due schedules may exist

    runs = (
        await db_session.execute(select(TestRun).where(TestRun.collection_id == ctx["collection"].id))
    ).scalars().all()
    assert runs == []

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_sweep_once_skips_not_yet_due_schedule(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    ctx = await _build_schedule(db_session, next_run_at=datetime.now(timezone.utc) + timedelta(hours=1))
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    await scheduler.sweep_once()

    await db_session.refresh(ctx["schedule"])
    assert ctx["schedule"].next_run_at > datetime.now(timezone.utc)  # untouched, still in the future

    runs = (
        await db_session.execute(select(TestRun).where(TestRun.collection_id == ctx["collection"].id))
    ).scalars().all()
    assert runs == []

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_sweep_once_advances_next_run_at_and_sets_last_run_at(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    ctx = await _build_schedule(db_session)
    original_next_run_at = ctx["schedule"].next_run_at
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    await scheduler.sweep_once()

    await db_session.refresh(ctx["schedule"])
    assert ctx["schedule"].next_run_at > original_next_run_at
    assert ctx["schedule"].next_run_at > datetime.now(timezone.utc)
    assert ctx["schedule"].last_run_at is not None

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_sweep_once_handles_collection_with_no_requests_gracefully(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    ctx = await _build_schedule(db_session, request_count=0)
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    await scheduler.sweep_once()  # must not raise

    await db_session.refresh(ctx["schedule"])
    assert ctx["schedule"].last_run_at is not None  # still advanced, not stuck retrying every sweep

    runs = (
        await db_session.execute(select(TestRun).where(TestRun.collection_id == ctx["collection"].id))
    ).scalars().all()
    assert runs == []  # nothing to run, so nothing was created

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_sweep_once_processes_multiple_due_schedules(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    ctx_a = await _build_schedule(db_session)
    ctx_b = await _build_schedule(db_session)
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    triggered = await scheduler.sweep_once()

    assert triggered >= 2  # at least ours; others may also be due in a shared database

    run_collection_ids = {
        row[0]
        for row in (
            await db_session.execute(
                select(TestRun.collection_id).where(
                    TestRun.collection_id.in_([ctx_a["collection"].id, ctx_b["collection"].id])
                )
            )
        ).all()
    }
    assert run_collection_ids == {ctx_a["collection"].id, ctx_b["collection"].id}

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_sweep_once_returns_zero_when_nothing_is_due(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    # "Nothing is due" is a whole-table claim, which a shared database can't
    # otherwise guarantee -- explicit, one-time setup for this specific
    # test's premise, not an assumption. _cleanup_schedules prevents this
    # file from re-polluting the table going forward; this line handles
    # whatever had already accumulated before that fixture existed.
    await db_session.execute(delete(Schedule))
    await db_session.commit()

    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue)
    triggered = await scheduler.sweep_once()

    assert triggered == 0

    await redis_client.delete(stream_queue.stream_name)


@pytest.mark.asyncio
async def test_run_forever_sweeps_repeatedly_until_shutdown(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    stream_queue = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    scheduler = CronScheduler(stream_queue, interval_seconds=0.5)
    shutdown_event = asyncio.Event()
    loop_task = asyncio.create_task(scheduler.run_forever(shutdown_event))

    # Schedule created *after* the loop has already done at least one empty
    # pass, proving it's actually looping, not just sweeping once at startup.
    await asyncio.sleep(0.6)
    await _build_schedule(db_session)

    deadline = time.monotonic() + 5.0
    found = False
    while time.monotonic() < deadline:
        entries = await stream_queue.consume("test-consumer", count=1, block_ms=200)
        if entries:
            found = True
            break

    shutdown_event.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert found, "run_forever did not pick up and trigger a schedule created after it started"

    await redis_client.delete(stream_queue.stream_name)