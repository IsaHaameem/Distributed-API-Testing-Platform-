"""Direct (non-HTTP) tests for the run chain-context Redis hash."""

import uuid

import pytest
from redis.asyncio import Redis

from app.queue.run_context import RunContext


@pytest.mark.asyncio
async def test_merge_and_get_all(redis_client: Redis) -> None:
    context = RunContext(redis_client)
    run_id = uuid.uuid4()

    await context.merge(run_id, {"authToken": "abc123"})
    result = await context.get_all(run_id)

    assert result == {"authToken": "abc123"}

    await redis_client.delete(context.context_key(run_id))


@pytest.mark.asyncio
async def test_merge_accumulates_across_multiple_calls(redis_client: Redis) -> None:
    context = RunContext(redis_client)
    run_id = uuid.uuid4()

    await context.merge(run_id, {"authToken": "abc123"})
    await context.merge(run_id, {"userId": "42"})
    result = await context.get_all(run_id)

    assert result == {"authToken": "abc123", "userId": "42"}

    await redis_client.delete(context.context_key(run_id))


@pytest.mark.asyncio
async def test_merge_overwrites_same_key(redis_client: Redis) -> None:
    context = RunContext(redis_client)
    run_id = uuid.uuid4()

    await context.merge(run_id, {"authToken": "first"})
    await context.merge(run_id, {"authToken": "second"})
    result = await context.get_all(run_id)

    assert result == {"authToken": "second"}

    await redis_client.delete(context.context_key(run_id))


@pytest.mark.asyncio
async def test_get_all_returns_empty_dict_for_unknown_run(redis_client: Redis) -> None:
    context = RunContext(redis_client)

    result = await context.get_all(uuid.uuid4())

    assert result == {}


@pytest.mark.asyncio
async def test_merge_with_empty_dict_is_a_no_op(redis_client: Redis) -> None:
    context = RunContext(redis_client)
    run_id = uuid.uuid4()

    await context.merge(run_id, {})

    assert await redis_client.exists(context.context_key(run_id)) == 0


@pytest.mark.asyncio
async def test_different_runs_have_independent_contexts(redis_client: Redis) -> None:
    context = RunContext(redis_client)
    run_a, run_b = uuid.uuid4(), uuid.uuid4()

    await context.merge(run_a, {"var": "for-a"})
    await context.merge(run_b, {"var": "for-b"})

    assert await context.get_all(run_a) == {"var": "for-a"}
    assert await context.get_all(run_b) == {"var": "for-b"}

    await redis_client.delete(context.context_key(run_a), context.context_key(run_b))