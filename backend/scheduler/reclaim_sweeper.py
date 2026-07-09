"""Periodically reclaims stream entries stuck in a dead (or merely
slow-to-ack) consumer's pending-entries list, and re-enqueues them as fresh
entries so a live worker can pick them up.

Wires StreamQueue.claim_stale() -- built and unit-tested since the streaming
queue was first written, but never called anywhere in production -- into an
actual running loop. Without this, a worker that crashes, or one that hits a
transient error after XREADGROUP but before XACK, leaves its in-flight tasks
stuck forever: XREADGROUP's ">" id never redelivers an entry already sitting
in a consumer's own pending list, dead or alive.

Same shape as RetrySweeper: claim, then re-enqueue-and-ack rather than
process directly -- this loop never touches TaskProcessor/Executor. Only the
worker pool executes target-API requests; this loop only moves ownership of
stream entries, exactly like RetrySweeper only moves entries between the
retry ZSET and the stream.

min_idle_ms must stay comfortably above the slowest a single processing
cycle can legitimately take, or a live-but-slow worker's in-flight task gets
duplicated (reclaimed and re-enqueued while the original is still working).
api_requests.timeout_ms tops out at 300_000ms (5 minutes); since a worker
processes its whole batch concurrently (asyncio.gather), one cycle's total
duration is bounded by its single slowest task, not the sum. The default
here is that ceiling plus margin for batch write/ack overhead -- not a
guess -- which means recovery for a genuinely dead worker is measured in
minutes, not seconds. That's a deliberate trade-off: this is an
eventual-recovery safety net, not fast failover, because tightening it risks
the much worse failure of reclaiming (and duplicating side effects against
the target API for) a request that was simply slow, not dead.
"""

import asyncio
import logging

from app.queue.stream_client import StreamQueue

logger = logging.getLogger("scheduler.reclaim_sweeper")

DEFAULT_RECLAIM_SWEEP_INTERVAL_SECONDS = 30
DEFAULT_RECLAIM_MIN_IDLE_MS = 360_000
DEFAULT_BATCH_SIZE = 50
RECLAIM_CONSUMER_NAME = "scheduler-reclaimer"


class ReclaimSweeper:
    def __init__(
        self,
        stream_queue: StreamQueue,
        *,
        interval_seconds: float = DEFAULT_RECLAIM_SWEEP_INTERVAL_SECONDS,
        min_idle_ms: int = DEFAULT_RECLAIM_MIN_IDLE_MS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        consumer_name: str = RECLAIM_CONSUMER_NAME,
    ) -> None:
        self.stream_queue = stream_queue
        self.interval_seconds = interval_seconds
        self.min_idle_ms = min_idle_ms
        self.batch_size = batch_size
        self.consumer_name = consumer_name

    async def sweep_once(self) -> int:
        """Reclaim and re-enqueue every entry idle longer than min_idle_ms.
        Returns how many were moved. A single pass, not a loop -- callers
        (the background loop, or a test) control the looping."""
        stale_entries = await self.stream_queue.claim_stale(
            self.consumer_name, min_idle_ms=self.min_idle_ms, count=self.batch_size
        )

        reclaimed_count = 0
        for entry in stale_entries:
            try:
                # Enqueue the fresh copy BEFORE acking the reclaimed one --
                # if enqueue fails, the entry simply stays claimed under our
                # name (idle time reset to 0 by claim_stale) and gets
                # reclaimed again next time it goes stale, rather than being
                # acked-and-lost with no fresh entry ever created.
                await self.stream_queue.enqueue(entry.task_id)
                await self.stream_queue.ack(entry.entry_id)
                reclaimed_count += 1
            except Exception:
                logger.exception(
                    "Failed to reclaim task %s (entry %s); it will be retried once it "
                    "goes stale again.",
                    entry.task_id,
                    entry.entry_id,
                )

        if reclaimed_count:
            logger.info("Reclaimed and re-enqueued %d stale task(s).", reclaimed_count)
        return reclaimed_count

    async def run_forever(self, shutdown_event: asyncio.Event) -> None:
        logger.info(
            "Reclaim sweeper started (interval=%.1fs, min_idle_ms=%d).",
            self.interval_seconds,
            self.min_idle_ms,
        )
        while not shutdown_event.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Reclaim sweep failed; will retry on the next interval.")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass  # normal case: the interval elapsed, loop again
        logger.info("Reclaim sweeper stopped.")
