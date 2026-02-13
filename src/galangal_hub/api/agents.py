"""
Agent API endpoints.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from galangal_hub.connection import manager
from galangal_hub.models import AgentWithState
from galangal_hub.storage import storage

router = APIRouter(prefix="/api/agents", tags=["agents"])
logger = logging.getLogger(__name__)


def _load_task_artifacts_from_db(*, task_name: str, project_path: str) -> dict[str, str]:
    """Load task artifacts from project's SQLite index, if available."""
    if not task_name:
        return {}
    try:
        from galangal.core.task_index import TaskIndex

        db_path = Path(project_path) / ".galangal" / "tasks.db"
        index = TaskIndex(db_path=db_path)
        artifacts: dict[str, str] = {}
        for name in index.list_task_artifacts(task_name=task_name):
            content = index.read_artifact(task_name=task_name, name=name)
            if content is None:
                continue
            artifacts[name] = content
        return artifacts
    except Exception:
        logger.debug("Failed loading artifacts from DB for task '%s'", task_name, exc_info=True)
        return {}


@router.get("")
async def list_agents() -> list[AgentWithState]:
    """Get all connected agents with their current state."""
    return manager.get_connected_agents()


@router.get("/needs-attention")
async def agents_needing_attention() -> list[AgentWithState]:
    """Get agents that need user attention (awaiting approval)."""
    return manager.get_agents_needing_attention()


@router.get("/history")
async def agent_history(limit: int = 50) -> list[dict]:
    """Get historical agent connections."""
    return await storage.get_agent_history(limit=limit)


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> AgentWithState:
    """Get a specific agent by ID."""
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.task:
        return agent

    db_artifacts = _load_task_artifacts_from_db(
        task_name=agent.task.task_name,
        project_path=agent.agent.project_path,
    )
    if not db_artifacts:
        return agent

    merged_artifacts = dict(db_artifacts)
    merged_artifacts.update(agent.artifacts)
    return agent.model_copy(update={"artifacts": merged_artifacts})
