"""Tests for task index database synchronization."""

import json
import sqlite3
from datetime import datetime, timezone

from galangal.config.loader import set_project_root
from galangal.core.artifacts import delete_artifact, write_artifact
from galangal.core.state import Stage, TaskType, WorkflowState, save_state
from galangal.core.task_index import TaskIndex
from galangal.core.tasks import set_active_task


def _make_state(task_name: str, description: str = "Test task") -> WorkflowState:
    return WorkflowState(
        stage=Stage.PM,
        attempt=1,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        task_description=description,
        task_name=task_name,
        task_type=TaskType.FEATURE,
    )


def test_save_state_updates_task_index(galangal_project):
    """Saving state should upsert the task in tasks.db."""
    set_project_root(galangal_project)

    state = _make_state("index-state-task", "Index from state")
    save_state(state)

    tasks = TaskIndex().list_tasks(statuses=("active",))
    names = [name for name, _, _, _ in tasks]
    assert "index-state-task" in names


def test_write_and_delete_artifact_updates_task_index(galangal_project):
    """Artifact write/delete operations should update the index rows."""
    set_project_root(galangal_project)

    state = _make_state("index-artifact-task")
    save_state(state)

    write_artifact("PLAN.md", "# Plan\n\nShip the feature.", task_name=state.task_name)

    db_path = TaskIndex().db_path
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT is_present FROM artifacts WHERE task_name = ? AND name = ?",
            (state.task_name, "PLAN.md"),
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 1

    deleted = delete_artifact("PLAN.md", task_name=state.task_name)
    assert deleted is True

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT is_present FROM artifacts WHERE task_name = ? AND name = ?",
            (state.task_name, "PLAN.md"),
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 0


def test_rebuild_backfills_existing_task_directories(galangal_project):
    """Rebuild should index pre-existing task directories from filesystem."""
    set_project_root(galangal_project)

    task_dir = galangal_project / "galangal-tasks" / "preexisting-task"
    task_dir.mkdir(parents=True)

    state_data = {
        "task_name": "preexisting-task",
        "task_description": "Backfill me",
        "task_type": "feature",
        "stage": "DEV",
        "attempt": 2,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (task_dir / "state.json").write_text(json.dumps(state_data, indent=2))
    (task_dir / "DEVELOPMENT.md").write_text("Implemented changes")

    index = TaskIndex()
    counts = index.rebuild()

    assert counts["active"] >= 1

    tasks = index.list_tasks(statuses=("active",))
    names = [name for name, _, _, _ in tasks]
    assert "preexisting-task" in names


def test_compact_done_markdown_keeps_plan_and_summary(galangal_project):
    """Compaction should remove extra done markdown files and keep PLAN/SUMMARY."""
    set_project_root(galangal_project)

    done_task = galangal_project / "galangal-tasks" / "done" / "finished-task"
    done_task.mkdir(parents=True)
    state_data = {
        "task_name": "finished-task",
        "task_description": "Finished task",
        "task_type": "feature",
        "stage": "COMPLETE",
        "attempt": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (done_task / "state.json").write_text(json.dumps(state_data, indent=2))
    (done_task / "PLAN.md").write_text("# Plan")
    (done_task / "SUMMARY.md").write_text("# Summary")
    (done_task / "DEV.md").write_text("details")
    (done_task / "QA.md").write_text("qa details")

    index = TaskIndex()
    result = index.compact_done_markdown()

    assert result["tasks"] == 1
    assert result["deleted"] == 2
    assert (done_task / "PLAN.md").exists()
    assert (done_task / "SUMMARY.md").exists()
    assert not (done_task / "DEV.md").exists()
    assert not (done_task / "QA.md").exists()

    with sqlite3.connect(index.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM artifacts WHERE task_name = ? AND is_present = 1",
            ("finished-task",),
        ).fetchall()
    names = {str(row[0]) for row in rows}
    assert {"PLAN.md", "SUMMARY.md", "DEV.md", "QA.md"}.issubset(names)


def test_compact_done_markdown_restores_missing_plan_and_summary(galangal_project):
    """Compaction should restore missing PLAN/SUMMARY files from DB when available."""
    set_project_root(galangal_project)

    done_task = galangal_project / "galangal-tasks" / "done" / "db-backed-task"
    done_task.mkdir(parents=True)
    state_data = {
        "task_name": "db-backed-task",
        "task_description": "DB-backed done task",
        "task_type": "feature",
        "stage": "COMPLETE",
        "attempt": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (done_task / "state.json").write_text(json.dumps(state_data, indent=2))
    (done_task / "DEV.md").write_text("legacy notes")

    index = TaskIndex()
    index.record_artifact_write(task_name="db-backed-task", name="PLAN.md", content="# Plan from DB")
    index.record_artifact_write(
        task_name="db-backed-task",
        name="SUMMARY.md",
        content="# Summary from DB",
    )

    result = index.compact_done_markdown()

    assert result["tasks"] == 1
    assert result["restored"] >= 0
    assert (done_task / "PLAN.md").read_text() == "# Plan from DB"
    assert (done_task / "SUMMARY.md").read_text() == "# Summary from DB"
    assert not (done_task / "DEV.md").exists()


def test_append_and_list_task_log_lines(galangal_project):
    """Task logs should be stored and returned in insertion order."""
    set_project_root(galangal_project)

    state = _make_state("logs-task")
    save_state(state)

    index = TaskIndex()
    index.append_task_log_line(task_name="logs-task", line="first", line_type="raw")
    index.append_task_log_lines(
        task_name="logs-task",
        lines=["second", "third"],
        line_type="error",
    )

    rows = index.list_task_log_lines(task_name="logs-task")
    assert len(rows) == 3
    assert rows[0]["line"] == "first"
    assert rows[0]["line_type"] == "raw"
    assert rows[1]["line"] == "second"
    assert rows[1]["line_type"] == "error"
    assert rows[2]["line"] == "third"
    assert rows[2]["line_type"] == "error"

    later = index.list_task_log_lines(task_name="logs-task", since_id=rows[0]["id"])
    assert len(later) == 2
    assert later[0]["line"] == "second"


def test_notify_output_persists_log_line_to_task_db(galangal_project):
    """notify_output should persist lines to task DB for the active task."""
    from galangal.hub.hooks import notify_output

    set_project_root(galangal_project)

    state = _make_state("hook-logs-task")
    save_state(state)
    set_active_task("hook-logs-task")

    notify_output("hello from hook", "raw")

    rows = TaskIndex().list_task_log_lines(task_name="hook-logs-task")
    assert any(row["line"] == "hello from hook" for row in rows)


def test_plan_and_summary_are_mirrored_to_task_folder(galangal_project):
    """PLAN.md and SUMMARY.md should be mirrored to task filesystem path."""
    set_project_root(galangal_project)

    state = _make_state("mirror-task")
    save_state(state)

    write_artifact("PLAN.md", "# Plan mirror", task_name="mirror-task")
    write_artifact("SUMMARY.md", "# Summary mirror", task_name="mirror-task")

    task_dir = galangal_project / "galangal-tasks" / "mirror-task"
    assert (task_dir / "PLAN.md").read_text() == "# Plan mirror"
    assert (task_dir / "SUMMARY.md").read_text() == "# Summary mirror"


def test_rebuild_preserves_plan_summary_files_but_deletes_other_artifacts(galangal_project):
    """Rebuild migration should keep mirrored files and delete non-mirrored artifacts."""
    set_project_root(galangal_project)

    task_dir = galangal_project / "galangal-tasks" / "mirror-rebuild-task"
    task_dir.mkdir(parents=True)
    state_data = {
        "task_name": "mirror-rebuild-task",
        "task_description": "Mirror rebuild",
        "task_type": "feature",
        "stage": "DEV",
        "attempt": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (task_dir / "state.json").write_text(json.dumps(state_data, indent=2))
    (task_dir / "PLAN.md").write_text("# Plan keep")
    (task_dir / "SUMMARY.md").write_text("# Summary keep")
    (task_dir / "DEV.md").write_text("remove me")

    index = TaskIndex()
    result = index.rebuild()

    assert result["migrated"] >= 3
    assert result["deleted"] >= 1
    assert (task_dir / "PLAN.md").exists()
    assert (task_dir / "SUMMARY.md").exists()
    assert not (task_dir / "DEV.md").exists()

    with sqlite3.connect(index.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM artifacts WHERE task_name = ? AND is_present = 1",
            ("mirror-rebuild-task",),
        ).fetchall()
    names = {str(row[0]) for row in rows}
    assert {"PLAN.md", "SUMMARY.md", "DEV.md"}.issubset(names)
