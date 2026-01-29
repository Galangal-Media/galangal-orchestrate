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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    PROMPT = "prompt"  # Send current prompt with options
    ARTIFACTS = "artifacts"  # Send artifact contents
    GITHUB_ISSUES = "github_issues"  # Response with GitHub issues list
    OUTPUT = "output"  # Streaming CLI output lines

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

    # Last known state (for resending on reconnect)
    _last_state: dict[str, Any] | None = field(default=None, init=False, repr=False)

    # Callbacks
    _action_handlers: list[Callable[[dict[str, Any]], None]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        # Generate deterministic agent_id from hostname + project_path
        # This ensures reconnects from the same project use the same ID
        hostname = platform.node()
        project_path_str = str(self.project_path)
        agent_id = self._generate_agent_id(hostname, project_path_str)

        self.agent_info = AgentInfo(
            agent_id=agent_id,
            hostname=hostname,
            project_name=self.project_name,
            project_path=project_path_str,
            agent_name=self.config.agent_name,
        )

    @staticmethod
    def _generate_agent_id(hostname: str, project_path: str) -> str:
        """Generate a deterministic agent ID from hostname and project path."""
        import hashlib
        # Create a stable hash from hostname + project_path
        key = f"{hostname}:{project_path}"
        hash_bytes = hashlib.sha256(key.encode()).digest()
        # Use first 16 bytes as UUID (UUID v4 format for compatibility)
        return str(uuid.UUID(bytes=hash_bytes[:16], version=4))

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
        # Store state for resending on reconnect
        state_data = {
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
        }
        self._last_state = state_data

        if not self._connected:
            return

        await self._send(MessageType.STATE_UPDATE, state_data)

    async def send_idle_state(self) -> None:
        """
        Send an idle state to hub indicating the agent is ready for a new task.

        This lets the hub UI know it can send CREATE_TASK actions.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.STATE_UPDATE,
            {
                "task_name": None,
                "task_description": None,
                "task_type": None,
                "stage": "IDLE",
                "attempt": 0,
                "awaiting_approval": False,
                "last_failure": None,
                "started_at": None,
                "stage_durations": {},
                "github_issue": None,
                "github_repo": None,
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

    async def send_prompt(
        self,
        prompt_type: str,
        message: str,
        options: list[dict[str, Any]],
        artifacts: list[str] | None = None,
        context: dict[str, Any] | None = None,
        questions: list[str] | None = None,
    ) -> None:
        """
        Send current prompt to hub.

        This notifies the hub that a prompt is being displayed to the user,
        allowing remote users to respond via the hub UI.

        Args:
            prompt_type: Type of prompt (e.g., "PLAN_APPROVAL", "COMPLETION").
            message: Message being displayed.
            options: List of option dicts with key, label, result fields.
            artifacts: List of artifact names relevant to this prompt.
            context: Optional additional context (stage, task_name, etc.).
            questions: List of questions for Q&A style prompts.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.PROMPT,
            {
                "prompt_type": prompt_type,
                "message": message,
                "options": options,
                "questions": questions or [],
                "artifacts": artifacts or [],
                "context": context or {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def send_artifacts(self, artifacts: dict[str, str]) -> None:
        """
        Send artifact contents to hub.

        Args:
            artifacts: Dict mapping artifact names to content.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.ARTIFACTS,
            {
                "artifacts": artifacts,
            },
        )

    async def clear_prompt(self) -> None:
        """
        Notify hub that the current prompt has been cleared/answered.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.PROMPT,
            {
                "prompt_type": None,  # None indicates prompt cleared
                "message": "",
                "options": [],
                "artifacts": [],
                "context": {},
            },
        )

    async def send_github_issues(
        self,
        issues: list[dict[str, Any]],
        request_id: str | None = None,
    ) -> None:
        """
        Send GitHub issues list to hub.

        Args:
            issues: List of issue dicts with number, title, labels, state, author.
            request_id: Optional request ID for correlating with request.
        """
        if not self._connected:
            return

        await self._send(
            MessageType.GITHUB_ISSUES,
            {
                "issues": issues,
                "request_id": request_id,
            },
        )

    async def send_output(
        self,
        line: str,
        line_type: str = "raw",
    ) -> None:
        """
        Send a CLI output line to hub.

        Args:
            line: The output line content.
            line_type: Type of line (raw, activity, tool, error).
        """
        if not self._connected:
            return

        await self._send(
            MessageType.OUTPUT,
            {
                "line": line,
                "line_type": line_type,
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
                # Resend last known state on reconnect
                if self._last_state:
                    try:
                        await self._send(MessageType.STATE_UPDATE, self._last_state)
                    except Exception:
                        pass
                break

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for WebSocket connection."""
        headers = {}
        if self.config.api_key:
            # Use both Authorization and X-API-Key headers
            # Some proxies (like Cloudflare) may strip Authorization headers
            headers["Authorization"] = f"Bearer {self.config.api_key}"
            headers["X-API-Key"] = self.config.api_key
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
