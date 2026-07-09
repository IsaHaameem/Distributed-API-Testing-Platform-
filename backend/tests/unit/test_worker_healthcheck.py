"""Unit tests for the worker healthcheck's pure filesystem logic --
read_worker_id has no I/O beyond a local file, and no dependency on Redis
or Postgres, so it's tested directly rather than through the full CLI.
"""

import uuid
from pathlib import Path

from worker.healthcheck import read_worker_id


def test_read_worker_id_returns_none_when_file_is_missing(tmp_path: Path) -> None:
    assert read_worker_id(tmp_path / "does_not_exist") is None


def test_read_worker_id_parses_a_valid_uuid(tmp_path: Path) -> None:
    worker_id = uuid.uuid4()
    path = tmp_path / "worker_id"
    path.write_text(str(worker_id))

    assert read_worker_id(path) == worker_id


def test_read_worker_id_tolerates_surrounding_whitespace(tmp_path: Path) -> None:
    worker_id = uuid.uuid4()
    path = tmp_path / "worker_id"
    path.write_text(f"  {worker_id}\n")

    assert read_worker_id(path) == worker_id


def test_read_worker_id_returns_none_for_malformed_content(tmp_path: Path) -> None:
    path = tmp_path / "worker_id"
    path.write_text("not-a-uuid")

    assert read_worker_id(path) is None


def test_read_worker_id_returns_none_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "worker_id"
    path.write_text("")

    assert read_worker_id(path) is None
