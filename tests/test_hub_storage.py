from pathlib import Path

import pytest

pytest.importorskip("aiosqlite")
from galangal_hub.storage import HubStorage


@pytest.mark.asyncio
async def test_task_artifacts_are_persisted_and_retrieved(tmp_path: Path):
    storage = HubStorage(db_path=tmp_path / "hub.db")
    await storage.initialize()
    try:
        await storage.upsert_task_artifacts(
            agent_id="agent-1",
            task_name="task-1",
            artifacts={"PLAN.md": "# Plan", "SUMMARY.md": "# Summary"},
            replace=True,
        )

        artifacts = await storage.get_task_artifacts(agent_id="agent-1", task_name="task-1")
        assert artifacts["PLAN.md"] == "# Plan"
        assert artifacts["SUMMARY.md"] == "# Summary"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_task_artifacts_replace_clears_old_entries(tmp_path: Path):
    storage = HubStorage(db_path=tmp_path / "hub.db")
    await storage.initialize()
    try:
        await storage.upsert_task_artifacts(
            agent_id="agent-1",
            task_name="task-1",
            artifacts={"PLAN.md": "# Old Plan", "DEV.md": "old dev notes"},
            replace=True,
        )
        await storage.upsert_task_artifacts(
            agent_id="agent-1",
            task_name="task-1",
            artifacts={"SUMMARY.md": "# New Summary"},
            replace=True,
        )

        artifacts = await storage.get_task_artifacts(agent_id="agent-1", task_name="task-1")
        assert artifacts == {"SUMMARY.md": "# New Summary"}
    finally:
        await storage.close()
