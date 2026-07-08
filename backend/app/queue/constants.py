"""Shared constants for the Redis Streams task queue -- the well-known
names both the worker (consumer) and run-orchestration (producer, a future
milestone) need to agree on.
"""

TASK_STREAM_NAME = "test_tasks"
WORKER_CONSUMER_GROUP = "workers"