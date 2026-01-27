"""
Task API endpoints.
"""

from typing import Any

from fastapi import APIRouter

from galangal_hub.connection import manager
from galangal_hub.storage import storage

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(
    agent_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Get recent tasks.

    Args:
        agent_id: Optional filter by agent.
        limit: Maximum number of tasks to return.
    """
    return await storage.get_recent_tasks(limit=limit, agent_id=agent_id)


@router.get("/active")
async def active_tasks() -> list[dict[str, Any]]:
    """Get all currently active tasks from connected agents."""
    agents = manager.get_connected_agents()
    tasks = []
    for agent in agents:
        if agent.task and agent.connected:
            tasks.append(
                {
                    "agent_id": agent.agent.agent_id,
                    "agent_name": agent.agent.agent_name,
                    "project_name": agent.agent.project_name,
                    **agent.task.model_dump(),
                }
            )
    return tasks


@router.get("/{agent_id}/{task_name}")
async def get_task(agent_id: str, task_name: str) -> dict[str, Any]:
    """Get details for a specific task."""
    # First check if it's an active task
    agent = manager.get_agent(agent_id)
    if agent and agent.task and agent.task.task_name == task_name:
        return {
            "agent": agent.agent.model_dump(),
            "task": agent.task.model_dump(),
            "active": True,
        }

    # Otherwise check history
    tasks = await storage.get_recent_tasks(agent_id=agent_id)
    for task in tasks:
        if task["task_name"] == task_name:
            return {
                "task": task,
                "active": False,
            }

    return {"error": "Task not found"}
