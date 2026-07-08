"""One-off script for manually verifying the full worker pipeline end to
end: creates a real test_task against a real external URL, enqueues it onto
the real stream, and polls Postgres until it completes, printing the
result. Requires a running worker: `docker compose up -d worker` first.

Not a pytest test -- run it directly:
    docker compose exec backend python tests/manual_enqueue_and_watch.py
"""

import asyncio
import time
import uuid

from sqlalchemy import select

from app.core.redis_client import get_redis_client
from app.core.security import hash_password
from app.database import AsyncSessionFactory
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.models.enums import HttpMethod, OrganizationRole, TestRunStatus, TestRunType, TestTaskStatus
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.queue.constants import TASK_STREAM_NAME, WORKER_CONSUMER_GROUP
from app.queue.stream_client import StreamQueue


async def main() -> None:
    redis_client = get_redis_client()
    stream_queue = StreamQueue(redis_client, TASK_STREAM_NAME, WORKER_CONSUMER_GROUP)
    await stream_queue.ensure_group()

    async with AsyncSessionFactory() as session:
        user = User(
            email=f"manual-enqueue-{uuid.uuid4()}@example.com",
            hashed_password=hash_password("a-strong-password-123"),
            full_name="Manual Enqueue",
        )
        session.add(user)
        await session.flush()

        org = Organization(name="Manual Enqueue Org", slug=f"manual-enqueue-{uuid.uuid4().hex[:12]}")
        session.add(org)
        await session.flush()
        session.add(
            OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
        )

        project = Project(organization_id=org.id, name="Project", created_by=user.id)
        session.add(project)
        await session.flush()

        collection = Collection(project_id=project.id, name="Collection")
        session.add(collection)
        await session.flush()

        api_request = ApiRequest(
            collection_id=collection.id,
            name="httpbin GET",
            method=HttpMethod.GET,
            url="https://httpbin.org/get",
        )
        session.add(api_request)
        await session.flush()

        test_run = TestRun(
            collection_id=collection.id,
            initiated_by=user.id,
            status=TestRunStatus.RUNNING,
            run_type=TestRunType.MANUAL,
            total_tasks=1,
            config={"environment_variables": {}},
        )
        session.add(test_run)
        await session.flush()

        test_task = TestTask(test_run_id=test_run.id, api_request_id=api_request.id)
        session.add(test_task)
        await session.flush()

        task_id = test_task.id
        await session.commit()

    print(f"Created test_task {task_id}")
    await stream_queue.enqueue(task_id)
    print(f"Enqueued onto '{TASK_STREAM_NAME}'. Waiting up to 20s for a worker to pick it up...")

    deadline = time.monotonic() + 20.0
    final_status = None
    while time.monotonic() < deadline:
        async with AsyncSessionFactory() as session:
            task = (await session.execute(select(TestTask).where(TestTask.id == task_id))).scalar_one()
            if task.status != TestTaskStatus.PENDING:
                final_status = task.status
                break
        await asyncio.sleep(0.5)

    if final_status is None:
        print("Timed out after 20s -- is a worker container actually running? (`docker compose ps`)")
        await redis_client.aclose()
        return

    print(f"Task status: {final_status.value}")

    async with AsyncSessionFactory() as session:
        request_result = (
            await session.execute(select(RequestResult).where(RequestResult.test_task_id == task_id))
        ).scalar_one_or_none()

    if request_result:
        print(f"  status_code: {request_result.status_code}")
        print(f"  latency_ms: {request_result.latency_ms}")
        print(f"  response_body_snippet: {request_result.response_body_snippet[:200]}")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())