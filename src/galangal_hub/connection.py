"""
WebSocket connection manager for tracking connected agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import WebSocket

from galangal_hub.models import AgentInfo, AgentWithState, HubAction, TaskState

logger = logging.getLogger(__name__)


@dataclass
class ConnectedAgent:
    """Tracks a connected agent and its state."""

    websocket: WebSocket
    info: AgentInfo
    task: TaskState | None = None
    connected: bool = True


@dataclass
class ConnectionManager:
    """Manages WebSocket connections from agents."""

    # agent_id -> ConnectedAgent
    _agents: dict[str, ConnectedAgent] = field(default_factory=dict)

    # Lock for thread-safe access (created lazily)
    _lock: asyncio.Lock | None = field(default=None)

    # Callbacks for state changes (for dashboard updates)
    _on_agent_change: list[Any] = field(default_factory=list)

    def _get_lock(self) -> asyncio.Lock:
        """Get or create the asyncio lock (lazy initialization)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def connect(self, agent_id: str, websocket: WebSocket, info: AgentInfo) -> None:
        """
        Register a new agent connection.

        Args:
            agent_id: Unique agent identifier.
            websocket: The WebSocket connection.
            info: Agent information.
        """
        async with self._get_lock():
            self._agents[agent_id] = ConnectedAgent(
                websocket=websocket,
                info=info,
                connected=True,
            )
        await self._notify_change()

    async def disconnect(self, agent_id: str) -> None:
        """
        Remove an agent connection.

        Args:
            agent_id: Agent to disconnect.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].connected = False
                # Keep agent info for a bit for UI display
                # Could add cleanup task later
        await self._notify_change()

    async def update_task_state(self, agent_id: str, state: TaskState) -> None:
        """
        Update the task state for an agent.

        Args:
            agent_id: Agent ID.
            state: New task state.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].task = state
        await self._notify_change()

    async def update_heartbeat(self, agent_id: str) -> None:
        """
        Update the last seen time for an agent.

        Args:
            agent_id: Agent ID.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].info.last_seen = datetime.now(timezone.utc)

    async def send_to_agent(self, agent_id: str, action: HubAction) -> bool:
        """
        Send an action to a specific agent.

        Args:
            agent_id: Target agent ID.
            action: Action to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        async with self._get_lock():
            agent = self._agents.get(agent_id)
            if not agent or not agent.connected:
                return False

            try:
                message = {
                    "type": "action",
                    "payload": action.model_dump(),
                }
                await agent.websocket.send_text(json.dumps(message))
                return True
            except Exception as e:
                logger.warning(f"Failed to send to agent {agent_id}: {e}")
                agent.connected = False
                return False

    def get_connected_agents(self) -> list[AgentWithState]:
        """
        Get all connected agents with their current state.

        Returns:
            List of agents with their task states.
        """
        return [
            AgentWithState(
                agent=agent.info,
                task=agent.task,
                connected=agent.connected,
            )
            for agent in self._agents.values()
        ]

    def get_agent(self, agent_id: str) -> AgentWithState | None:
        """
        Get a specific agent by ID.

        Args:
            agent_id: Agent ID to look up.

        Returns:
            Agent with state, or None if not found.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        return AgentWithState(
            agent=agent.info,
            task=agent.task,
            connected=agent.connected,
        )

    def get_agents_needing_attention(self) -> list[AgentWithState]:
        """
        Get agents that need user attention (awaiting approval).

        Returns:
            List of agents awaiting approval.
        """
        return [
            AgentWithState(
                agent=agent.info,
                task=agent.task,
                connected=agent.connected,
            )
            for agent in self._agents.values()
            if agent.task and agent.task.awaiting_approval and agent.connected
        ]

    def on_change(self, callback: Any) -> None:
        """Register a callback for agent state changes."""
        self._on_agent_change.append(callback)

    async def _notify_change(self) -> None:
        """Notify all registered callbacks of a state change."""
        for callback in self._on_agent_change:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.warning(f"Callback error: {e}")


# Global connection manager instance
manager = ConnectionManager()
