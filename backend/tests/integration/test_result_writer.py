"""Integration tests for the batched result writer -- exercises real
Postgres writes, including the bulk UPDATE-by-primary-key path and the
run-completion transition."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.models.enums import HttpMethod, OrganizationRole, TestRunStatus, TestRunType, TestTaskStatus
from app.models.execution_log import ExecutionLog
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.models.worker import Worker
from worker.result_writer import ResultWriter, TaskOutcome


async def _build_test_run(
    session: AsyncSession, *, total_tasks: int
) -> tuple[TestRun, TestTask, Worker]:
    user = User(
        email=f"writer-test-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("a-strong-password-123"),
        full_name="Writer Test User",
    )
    session.add(user)
    await session.flush()

    org = Organization(name="Writer Test Org", slug=f"writer-test-{uuid.uuid4().hex[:12]}")
    session.add(org)
    await session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))

    project = Project(organization_id=org.id, name="Project", created_by=user.id)
    session.add(project)
    await session.flush()

    collection = Collection(project_id=project.id, name="Collection")
    session.add(collection)
    await session.flush()

    api_request = ApiRequest(
        collection_id=collection.id, name="Request", method=HttpMethod.GET, url="https://example.com"
    )
    session.add(api_request)
    await session.flush()

    test_run = TestRun(
        collection_id=collection.id,
        initiated_by=user.id,
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=total_tasks,
    )
    session.add(test_run)
    await session.flush()

    test_task = TestTask(test_run_id=test_run.id, api_request_id=api_request.id)
    session.add(test_task)
    await session.flush()

    worker = Worker(hostname="writer-test-worker", pid=1)
    session.add(worker)
    await session.flush()

    return test_run, test_task, worker


def _completed_outcome(test_task: TestTask, test_run_id: uuid.UUID, worker_id: uuid.UUID) -> TaskOutcome:
    return TaskOutcome(
        test_task_id=test_task.id,
        test_run_id=test_run_id,
        attempt_number=1,
        new_status=TestTaskStatus.COMPLETED,
        status_code=200,
        latency_ms=42,
        response_headers={"content-type": "application/json"},
        response_body='{"ok": true}',
        assertions_passed=True,
        error_message=None,
        executed_by_worker_id=worker_id,
        retry_count=0,
        next_retry_at=None,
    )


@pytest.mark.asyncio
async def test_write_batch_updates_task_status(db_session: AsyncSession) -> None:
    test_run, test_task, worker = await _build_test_run(db_session, total_tasks=1)
    outcome = _completed_outcome(test_task, test_run.id, worker.id)

    await ResultWriter().write_batch([outcome], db_session)

    await db_session.refresh(test_task)
    assert test_task.status == TestTaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_write_batch_creates_request_result_and_log(db_session: AsyncSession) -> None:
    test_run, test_task, worker = await _build_test_run(db_session, total_tasks=1)
    outcome = _completed_outcome(test_task, test_run.id, worker.id)

    await ResultWriter().write_batch([outcome], db_session)

    results = (
        await db_session.execute(select(RequestResult).where(RequestResult.test_task_id == test_task.id))
    ).scalars().all()
    logs = (
        await db_session.execute(select(ExecutionLog).where(ExecutionLog.test_task_id == test_task.id))
    ).scalars().all()

    assert len(results) == 1
    assert results[0].status_code == 200
    assert len(logs) == 1
    assert logs[0].level.value == "info"


@pytest.mark.asyncio
async def test_write_batch_truncates_long_response_body(db_session: AsyncSession) -> None:
    test_run, test_task, worker = await _build_test_run(db_session, total_tasks=1)
    outcome = _completed_outcome(test_task, test_run.id, worker.id)
    outcome.response_body = "x" * 10_000

    await ResultWriter().write_batch([outcome], db_session)

    result = (
        await db_session.execute(select(RequestResult).where(RequestResult.test_task_id == test_task.id))
    ).scalar_one()
    assert len(result.response_body_snippet) == 4096


@pytest.mark.asyncio
async def test_write_batch_increments_run_counters(db_session: AsyncSession) -> None:
    test_run, test_task, worker = await _build_test_run(db_session, total_tasks=2)
    outcome = _completed_outcome(test_task, test_run.id, worker.id)

    await ResultWriter().write_batch([outcome], db_session)

    await db_session.refresh(test_run)
    assert test_run.completed_tasks == 1
    assert test_run.failed_tasks == 0


@pytest.mark.asyncio
async def test_write_batch_marks_run_completed_when_last_task_finishes(db_session: AsyncSession) -> None:
    test_run, test_task, worker = await _build_test_run(db_session, total_tasks=1)
    outcome = _completed_outcome(test_task, test_run.id, worker.id)

    await ResultWriter().write_batch([outcome], db_session)

    await db_session.refresh(test_run)
    assert test_run.status == TestRunStatus.COMPLETED
    assert test_run.completed_at is not None


@pytest.mark.asyncio
async def test_write_batch_does_not_complete_run_with_tasks_remaining(db_session: AsyncSession) -> None:
    test_run, test_task, worker = await _build_test_run(db_session, total_tasks=2)
    outcome = _completed_outcome(test_task, test_run.id, worker.id)

    await ResultWriter().write_batch([outcome], db_session)

    await db_session.refresh(test_run)
    assert test_run.status == TestRunStatus.RUNNING


@pytest.mark.asyncio
async def test_write_batch_handles_multiple_outcomes_in_one_call(db_session: AsyncSession) -> None:
    test_run, test_task_1, worker = await _build_test_run(db_session, total_tasks=2)
    test_task_2 = TestTask(test_run_id=test_run.id, api_request_id=test_task_1.api_request_id)
    db_session.add(test_task_2)
    await db_session.flush()

    outcome_1 = _completed_outcome(test_task_1, test_run.id, worker.id)
    outcome_2 = _completed_outcome(test_task_2, test_run.id, worker.id)

    await ResultWriter().write_batch([outcome_1, outcome_2], db_session)

    await db_session.refresh(test_run)
    assert test_run.completed_tasks == 2
    assert test_run.status == TestRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_write_batch_with_no_outcomes_does_nothing(db_session: AsyncSession) -> None:
    await ResultWriter().write_batch([], db_session)  # should not raise