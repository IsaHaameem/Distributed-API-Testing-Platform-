"""Unit tests for exponential backoff computation -- pure math, no Redis needed."""

from app.queue.retry_queue import compute_backoff_seconds


def test_backoff_grows_with_retry_count() -> None:
    assert compute_backoff_seconds(0) == 2
    assert compute_backoff_seconds(1) == 4
    assert compute_backoff_seconds(2) == 8
    assert compute_backoff_seconds(3) == 16


def test_backoff_is_capped_at_sixty_seconds() -> None:
    assert compute_backoff_seconds(10) == 60
    assert compute_backoff_seconds(100) == 60