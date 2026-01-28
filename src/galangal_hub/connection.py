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

from galangal_hub.models import AgentInfo, AgentWithState, HubAction, PromptData, TaskState

logger = logging.getLogger(__name__)


@dataclass
class ConnectedAgent:
    """Tracks a connected agent and its state."""

    websocket: WebSocket
    info: AgentInfo
    task: TaskState | None = None
    connected: bool = True
    current_prompt: PromptData | None = None  # Currently displayed prompt
    artifacts: dict[str, str] = field(default_factory=dict)  # Artifact name -> content
    github_issues: list[dict] = field(default_factory=list)  # Cached GitHub issues
    github_issues_updated: datetime | None = None  # When issues were last updated
    output_lines: list[dict] = field(default_factory=list)  # Recent output lines (ring buffer)
    output_max_lines: int = 200  # Max lines to keep


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
                # Remove the agent entirely - they'll reconnect with same ID if they come back
                del self._agents[agent_id]
        await self._notify_change()

    async def update_task_state(self, agent_id: str, state: TaskState | None) -> TaskState | None:
        """
        Update the task state for an agent.

        Args:
            agent_id: Agent ID.
            state: New task state, or None if agent is idle.

        Returns:
            The previous task state (for detecting task changes).
        """
        previous_state = None
        async with self._get_lock():
            if agent_id in self._agents:
                previous_state = self._agents[agent_id].task
                self._agents[agent_id].task = state
        await self._notify_change()
        return previous_state

    async def update_heartbeat(self, agent_id: str) -> None:
        """
        Update the last seen time for an agent.

        Args:
            agent_id: Agent ID.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].info.last_seen = datetime.now(timezone.utc)

    async def update_prompt(self, agent_id: str, prompt: PromptData | None) -> None:
        """
        Update the current prompt for an agent.

        Args:
            agent_id: Agent ID.
            prompt: Prompt data, or None to clear.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].current_prompt = prompt
        await self._notify_change()

    async def update_artifacts(self, agent_id: str, artifacts: dict[str, str]) -> None:
        """
        Update the artifacts for an agent.

        Args:
            agent_id: Agent ID.
            artifacts: Dict mapping artifact names to content.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].artifacts.update(artifacts)
        await self._notify_change()

    async def clear_prompt(self, agent_id: str) -> None:
        """
        Clear the current prompt for an agent.

        Args:
            agent_id: Agent ID.
        """
        await self.update_prompt(agent_id, None)

    async def update_github_issues(self, agent_id: str, issues: list[dict]) -> None:
        """
        Update the cached GitHub issues for an agent.

        Args:
            agent_id: Agent ID.
            issues: List of issue dicts.
        """
        async with self._get_lock():
            if agent_id in self._agents:
                self._agents[agent_id].github_issues = issues
                self._agents[agent_id].github_issues_updated = datetime.now(timezone.utc)
        await self._notify_change()

    def get_github_issues(self, agent_id: str) -> list[dict]:
        """
        Get cached GitHub issues for an agent.

        Args:
            agent_id: Agent ID.

        Returns:
            List of issue dicts, or empty list if not available.
        """
        agent = self._agents.get(agent_id)
        if agent:
            return agent.github_issues
        return []

    async def append_output(self, agent_id: str, line: str, line_type: str) -> None:
        """
        Append an output line for an agent.

        Args:
            agent_id: Agent ID.
            line: Output line content.
            line_type: Type of line (raw, activity, tool, error).
        """
        async with self._get_lock():
            if agent_id in self._agents:
                agent = self._agents[agent_id]
                agent.output_lines.append({
                    "line": line,
                    "line_type": line_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                # Keep only recent lines (ring buffer)
                if len(agent.output_lines) > agent.output_max_lines:
                    agent.output_lines = agent.output_lines[-agent.output_max_lines:]
        # Don't call _notify_change for every line - too noisy

    def get_output_lines(self, agent_id: str, since_index: int = 0) -> list[dict]:
        """
        Get output lines for an agent.

        Args:
            agent_id: Agent ID.
            since_index: Return lines after this index (for incremental fetch).

        Returns:
            List of output line dicts.
        """
        agent = self._agents.get(agent_id)
        if agent:
            return agent.output_lines[since_index:]
        return []

    def clear_output(self, agent_id: str) -> None:
        """Clear output lines for an agent (e.g., when new task starts)."""
        agent = self._agents.get(agent_id)
        if agent:
            agent.output_lines = []

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

        Only returns agents that are currently connected (filters out stale disconnected agents).

        Returns:
            List of agents with their task states.
        """
        return [
            AgentWithState(
                agent=agent.info,
                task=agent.task,
                connected=agent.connected,
                current_prompt=agent.current_prompt,
                artifacts=agent.artifacts,
            )
            for agent in self._agents.values()
            if agent.connected  # Only show connected agents
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
            current_prompt=agent.current_prompt,
            artifacts=agent.artifacts,
        )

    def get_agents_needing_attention(self) -> list[AgentWithState]:
        """
        Get agents that need user attention (awaiting approval or with active prompt).

        Returns:
            List of agents awaiting user input.
        """
        return [
            AgentWithState(
                agent=agent.info,
                task=agent.task,
                connected=agent.connected,
                current_prompt=agent.current_prompt,
                artifacts=agent.artifacts,
            )
            for agent in self._agents.values()
            if agent.connected and (
                (agent.task and agent.task.awaiting_approval) or agent.current_prompt
            )
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
