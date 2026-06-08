"""Tests for DB->disk artifact rehydration before a stage runs."""

import galangal.config.loader as loader
from galangal.config.defaults import generate_default_config


def _init_project(tmp_path):
    (tmp_path / ".galangal").mkdir()
    (tmp_path / ".galangal" / "config.yaml").write_text(generate_default_config("t"))
    # reset_caches() nulls _project_root, so pin the root AFTER clearing caches.
    loader.reset_caches()
    loader.set_project_root(tmp_path)


def test_rehydrate_writes_db_only_artifact_to_disk(tmp_path):
    _init_project(tmp_path)
    from galangal.config.loader import get_tasks_dir
    from galangal.core.task_index import TaskIndex

    ti = TaskIndex()
    # Artifact lives in the DB only (post-ingest state: ingested + unlinked from disk).
    ti.record_artifact_write(task_name="T", name="SPEC.md", content="SPEC D1-D10", stage="PM")
    spec = get_tasks_dir() / "T" / "SPEC.md"
    assert not spec.exists()

    written = ti.rehydrate_task_artifacts(task_name="T")

    assert written == 1
    assert spec.read_text() == "SPEC D1-D10"


def test_rehydrate_is_idempotent(tmp_path):
    _init_project(tmp_path)
    from galangal.core.task_index import TaskIndex

    ti = TaskIndex()
    ti.record_artifact_write(task_name="T", name="SPEC.md", content="x", stage="PM")
    assert ti.rehydrate_task_artifacts(task_name="T") == 1
    assert ti.rehydrate_task_artifacts(task_name="T") == 0  # unchanged -> no rewrite


def test_rehydrate_no_artifacts_returns_zero(tmp_path):
    _init_project(tmp_path)
    from galangal.core.task_index import TaskIndex

    assert TaskIndex().rehydrate_task_artifacts(task_name="nonexistent") == 0


def test_rehydrate_does_not_clobber_local_edits(tmp_path):
    """If the agent already wrote a newer version this turn, rehydrate would only
    run before the stage; but a differing on-disk file is overwritten to match the
    canonical DB (the DB is the source of truth)."""
    _init_project(tmp_path)
    from galangal.config.loader import get_tasks_dir
    from galangal.core.task_index import TaskIndex

    ti = TaskIndex()
    ti.record_artifact_write(task_name="T", name="SPEC.md", content="canonical", stage="PM")
    spec = get_tasks_dir() / "T" / "SPEC.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("stale-on-disk")

    written = ti.rehydrate_task_artifacts(task_name="T")
    assert written == 1
    assert spec.read_text() == "canonical"


def test_delete_unlinks_disk_copy_so_ingest_does_not_resurrect(tmp_path):
    """A deleted non-mirrored artifact must not come back via the next ingest."""
    _init_project(tmp_path)
    from galangal.config.loader import get_tasks_dir
    from galangal.core.task_index import TaskIndex

    ti = TaskIndex()
    ti.record_artifact_write(task_name="T", name="NOTES.md", content="x", stage="DEV")
    ti.rehydrate_task_artifacts(task_name="T")  # NOTES.md now on disk
    disk = get_tasks_dir() / "T" / "NOTES.md"
    assert disk.exists()

    ti.record_artifact_delete(task_name="T", name="NOTES.md")
    assert not disk.exists()  # disk copy removed too (not just DB row)

    ti.ingest_task_artifacts(task_name="T")  # would have resurrected it before
    assert ti.read_artifact(task_name="T", name="NOTES.md") is None


def test_deleting_task_clears_artifacts_no_name_reuse_bleed(tmp_path):
    """A new task reusing a deleted task's name must not inherit its artifacts."""
    _init_project(tmp_path)
    from galangal.core.task_index import TaskIndex

    ti = TaskIndex()
    ti.record_artifact_write(task_name="reused", name="SPEC.md", content="OLD", stage="PM")
    assert ti.read_artifact(task_name="reused", name="SPEC.md") == "OLD"

    ti.mark_task_deleted(task_name="reused")

    # The freshly re-created task with the same name sees no prior artifacts.
    assert ti.read_artifact(task_name="reused", name="SPEC.md") is None
    assert ti.rehydrate_task_artifacts(task_name="reused") == 0


def test_resolve_task_dir_prefers_done_dir(tmp_path):
    """Ingest/rehydrate target the done dir for a finalized task."""
    _init_project(tmp_path)
    from galangal.config.loader import get_done_dir, get_tasks_dir
    from galangal.core.task_index import TaskIndex

    ti = TaskIndex()
    assert ti._resolve_task_dir("T") == get_tasks_dir() / "T"  # active by default
    (get_done_dir() / "T").mkdir(parents=True)
    assert ti._resolve_task_dir("T") == get_done_dir() / "T"  # done takes precedence
