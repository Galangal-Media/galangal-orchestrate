from datetime import datetime, timezone
from pathlib import Path

import pytest

from galangal_hub.models import AgentInfo, AgentWithState, TaskState

pytest.importorskip("fastapi")
from galangal_hub.api import agents as agents_api


def _make_connected_agent(*, project_path: Path, task_name: str) -> AgentWithState:
    now = datetime.now(timezone.utc).isoformat()
    return AgentWithState(
        agent=AgentInfo(
            agent_id="agent-1",
            hostname="test-host",
            project_name="Test Project",
            project_path=str(project_path),
            agent_name="Test Agent",
        ),
        task=TaskState(
            task_name=task_name,
            task_description="Test task",
            task_type="feature",
            stage="DEV",
            attempt=1,
            awaiting_approval=False,
            started_at=now,
        ),
        connected=True,
        artifacts={"LIVE.md": "live update"},
    )


@pytest.mark.asyncio
async def test_get_agent_loads_artifacts_from_hub_db(monkeypatch: pytest.MonkeyPatch, galangal_project: Path):
    task_name = "task-from-db"
    agent = _make_connected_agent(project_path=galangal_project, task_name=task_name)
    monkeypatch.setattr(agents_api.manager, "get_agent", lambda _agent_id: agent)

    async def _mock_get_task_artifacts(*, agent_id: str, task_name: str) -> dict[str, str]:
        assert agent_id == "agent-1"
        assert task_name == "task-from-db"
        return {
            "PLAN.md": "# Plan from DB",
            "SUMMARY.md": "# Summary from DB",
        }

    monkeypatch.setattr(agents_api.storage, "get_task_artifacts", _mock_get_task_artifacts)

    result = await agents_api.get_agent("agent-1")

    assert result.artifacts["LIVE.md"] == "live update"
    assert result.artifacts["PLAN.md"] == "# Plan from DB"
    assert result.artifacts["SUMMARY.md"] == "# Summary from DB"
