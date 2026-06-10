"""Tests for locked/atomic active-task tracking."""

from pathlib import Path

from galangal.config.loader import set_project_root
from galangal.core.tasks import clear_active_task, get_active_task, set_active_task


def test_set_get_round_trip(tmp_path: Path):
    set_project_root(tmp_path)
    (tmp_path / ".galangal").mkdir()

    assert get_active_task() is None
    set_active_task("issue-42-abc")
    assert get_active_task() == "issue-42-abc"

    # Overwrite is atomic and observable.
    set_active_task("other-task")
    assert get_active_task() == "other-task"

    clear_active_task()
    assert get_active_task() is None


def test_blank_active_file_reads_as_none(tmp_path: Path):
    set_project_root(tmp_path)
    (tmp_path / ".galangal").mkdir()
    set_active_task("   ")
    assert get_active_task() is None
