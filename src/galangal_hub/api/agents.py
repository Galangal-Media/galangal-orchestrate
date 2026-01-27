"""
Agent API endpoints.
"""

from fastapi import APIRouter, HTTPException

from galangal_hub.connection import manager
from galangal_hub.models import AgentWithState
from galangal_hub.storage import storage

router = APIRouter(prefix="/api/agents", tags=["agents"])


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
    return agent
