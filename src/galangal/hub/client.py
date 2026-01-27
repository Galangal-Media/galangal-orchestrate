"""
WebSocket client for connecting to Galangal Hub.

Handles:
- Connection lifecycle (connect, disconnect, reconnect)
- State synchronization (sending workflow state updates)
- Event publishing (stage transitions, approvals, etc.)
- Remote action handling (receiving commands from hub)
"""

from __future__ import annotations

import asyncio
import json
import platform
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from galangal.core.state import WorkflowState
    from galangal.hub.config import HubConfig


class MessageType(str, Enum):
    """Types of messages in the hub protocol."""

    # Agent -> Hub
    REGISTER = "register"
    STATE_UPDATE = "state_update"
    EVENT = "event"
    HEARTBEAT = "heartbeat"

    # Hub -> Agent
    ACTION = "action"
    ACTION_RESULT = "action_result"


class EventType(str, Enum):
    """Types of workflow events."""

    STAGE_START = "stage_start"
    STAGE_COMPLETE = "stage_complete"
    STAGE_FAIL = "stage_fail"
    APPROVAL_NEEDED = "approval_needed"
    ROLLBACK = "rollback"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"


@dataclass
class AgentInfo:
    """Information about this agent."""

    agent_id: str
    hostname: str
    project_name: str
    project_path: str
    agent_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "hostname": self.hostname,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "agent_name": self.agent_name or self.hostname,
        }


@dataclass
class HubClient:
    """WebSocket client for Galangal Hub communication."""

    config: HubConfig
    project_name: str
    project_path: Path
    agent_info: AgentInfo = field(init=False)

    # Connection state
    _websocket: Any = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False)
    _reconnect_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _heartbeat_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _receive_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    # Callbacks
    _action_handlers: list[Callable[[dict[str, Any]], None]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.agent_info = AgentInfo(
            agent_id=str(uuid.uuid4()),
            hostname=platform.node(),
            project_name=self.project_name,
            project_path=str(self.project_path),
            agent_name=self.config.agent_name,
        )

    @property
    def connected(self) -> bool:
        """Check if connected to hub."""
        return self._connected

    def on_action(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for incoming actions from hub."""
        self._action_handlers.append(callback)

    async def connect(self) -> bool:
        """
        Connect to the hub server.

        Returns:
            True if connection successful, False otherwise.
        """
        if not self.config.enabled:
            return False

        try:
            import websockets

            self._websocket = await websockets.connect(
                self.config.url,
                additional_headers=self._get_auth_headers(),
            )
            self._connected = True

            # Send registration message
            await self._send(MessageType.REGISTER, self.agent_info.to_dict())

            # Start background tasks
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._receive_task = asyncio.create_task(self._receive_loop())

            return True

        except Exception as e:
            self._connected = False
            # Log error but don't fail - hub is optional
            import structlog

            logger = structlog.get_logger()
            logger.warning("hub_connection_failed", error=str(e), url=self.config.url)
            return False

    async def disconnect(self) -> None:
        """Disconnect from the hub server."""
        self._connected = False

        # Cancel background tasks
        for task in [self._heartbeat_task, self._receive_task, self._reconnect_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close websocket
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

    async def send_state(self, state: WorkflowState) -> None:
        """
        Send current workflow state to hub.

        Args:
            state: Current workflow state.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.STATE_UPDATE,
            {
                "task_name": state.task_name,
                "task_description": state.task_description,
                "task_type": state.task_type.value,
                "stage": state.stage.value,
                "attempt": state.attempt,
                "awaiting_approval": state.awaiting_approval,
                "last_failure": state.last_failure,
                "started_at": state.started_at,
                "stage_durations": state.stage_durations,
                "github_issue": state.github_issue,
                "github_repo": state.github_repo,
            },
        )

    async def send_event(
        self,
        event_type: EventType,
        data: dict[str, Any] | None = None,
    ) -> None:
        """
        Send a workflow event to hub.

        Args:
            event_type: Type of event.
            data: Optional event data.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.EVENT,
            {
                "event_type": event_type.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data or {},
            },
        )

    async def _send(self, msg_type: MessageType, payload: dict[str, Any]) -> None:
        """Send a message to the hub."""
        if not self._websocket:
            return

        try:
            message = {
                "type": msg_type.value,
                "agent_id": self.agent_info.agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            await self._websocket.send(json.dumps(message))
        except Exception:
            # Connection lost, will reconnect
            self._connected = False

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to hub."""
        while self._connected:
            try:
                await asyncio.sleep(self.config.heartbeat_interval)
                if self._connected:
                    await self._send(MessageType.HEARTBEAT, {})
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _receive_loop(self) -> None:
        """Receive and handle messages from hub."""
        while self._connected and self._websocket:
            try:
                message = await self._websocket.recv()
                data = json.loads(message)
                await self._handle_message(data)
            except asyncio.CancelledError:
                break
            except Exception:
                # Connection lost
                self._connected = False
                asyncio.create_task(self._reconnect())
                break

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle an incoming message from hub."""
        msg_type = data.get("type")

        if msg_type == MessageType.ACTION.value:
            # Remote action request
            for handler in self._action_handlers:
                try:
                    handler(data.get("payload", {}))
                except Exception:
                    pass

    async def _reconnect(self) -> None:
        """Attempt to reconnect to hub."""
        while not self._connected:
            await asyncio.sleep(self.config.reconnect_interval)
            if await self.connect():
                break

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for WebSocket connection."""
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


# Global client instance (initialized on first use)
_hub_client: HubClient | None = None


def get_hub_client() -> HubClient | None:
    """Get the global hub client instance."""
    return _hub_client


def set_hub_client(client: HubClient | None) -> None:
    """Set the global hub client instance."""
    global _hub_client
    _hub_client = client
