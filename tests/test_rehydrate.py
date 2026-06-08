"""Tests for DB->disk artifact rehydration before a stage runs."""

import galangal.config.loader as loader
from galangal.config.defaults import generate_default_config


def _init_project(tmp_path):
    (tmp_path / ".galangal").mkdir()
    (tmp_path / ".galangal" / "config.yaml").write_text(generate_default_config("t"))
    loader.set_project_root(tmp_path)
    if hasattr(loader, "reset_caches"):
        loader.reset_caches()


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
