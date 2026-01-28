"""
Handler for remote actions from hub.

Processes incoming action requests and coordinates with the TUI
to execute them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """Types of actions that can be received from hub."""

    APPROVE = "approve"
    REJECT = "reject"
    SKIP = "skip"
    ROLLBACK = "rollback"
    INTERRUPT = "interrupt"
    RESPONSE = "response"  # Response to any prompt (not just approval)
    CREATE_TASK = "create_task"  # Create a new task
    FETCH_GITHUB_ISSUES = "fetch_github_issues"  # Request GitHub issues list


@dataclass
class PendingAction:
    """A pending action from the hub."""

    action_type: ActionType
    task_name: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PendingAction:
        """Create from dictionary (hub message payload)."""
        return cls(
            action_type=ActionType(d["action_type"]),
            task_name=d["task_name"],
            data=d.get("data", {}),
        )


@dataclass
class PendingResponse:
    """A pending response to a prompt from the hub."""

    prompt_type: str  # The prompt type this responds to
    result: str  # The selected option result (e.g., "yes", "no", "quit")
    text_input: str | None = None  # Optional text input for prompts that need it

    @classmethod
    def from_action(cls, action: PendingAction) -> PendingResponse:
        """Create from a RESPONSE action."""
        data = action.data
        return cls(
            prompt_type=data.get("prompt_type", ""),
            result=data.get("result", ""),
            text_input=data.get("text_input"),
        )


@dataclass
class PendingTaskCreate:
    """A pending request to create a new task from the hub."""

    task_name: str | None = None  # Manual task name (if not from issue)
    task_description: str | None = None  # Manual description
    task_type: str = "feature"  # Task type (feature, bug_fix, etc.)
    github_issue: int | None = None  # GitHub issue number
    github_repo: str | None = None  # GitHub repo (owner/repo)

    @classmethod
    def from_action(cls, action: PendingAction) -> PendingTaskCreate:
        """Create from a CREATE_TASK action."""
        data = action.data
        return cls(
            task_name=data.get("task_name"),
            task_description=data.get("task_description"),
            task_type=data.get("task_type", "feature"),
            github_issue=data.get("github_issue"),
            github_repo=data.get("github_repo"),
        )


class ActionHandler:
    """
    Handles incoming actions from the hub.

    The handler maintains a queue of pending actions that the TUI
    can poll and process during its normal operation.
    """

    def __init__(self) -> None:
        self._pending: PendingAction | None = None
        self._pending_response: PendingResponse | None = None
        self._pending_task_create: PendingTaskCreate | None = None
        self._callbacks: list[Callable[[PendingAction], None]] = []
        self._response_callbacks: list[Callable[[PendingResponse], None]] = []
        self._task_create_callbacks: list[Callable[[PendingTaskCreate], None]] = []

    @property
    def has_pending_action(self) -> bool:
        """Check if there is a pending action."""
        return self._pending is not None

    @property
    def has_pending_response(self) -> bool:
        """Check if there is a pending response."""
        return self._pending_response is not None

    @property
    def has_pending_task_create(self) -> bool:
        """Check if there is a pending task creation request."""
        return self._pending_task_create is not None

    def get_pending_action(self) -> PendingAction | None:
        """Get and clear the pending action."""
        action = self._pending
        self._pending = None
        return action

    def peek_pending_action(self) -> PendingAction | None:
        """Get the pending action without clearing it."""
        return self._pending

    def get_pending_response(self) -> PendingResponse | None:
        """Get and clear the pending response."""
        response = self._pending_response
        self._pending_response = None
        return response

    def peek_pending_response(self) -> PendingResponse | None:
        """Get the pending response without clearing it."""
        return self._pending_response

    def get_pending_task_create(self) -> PendingTaskCreate | None:
        """Get and clear the pending task creation request."""
        task_create = self._pending_task_create
        self._pending_task_create = None
        return task_create

    def peek_pending_task_create(self) -> PendingTaskCreate | None:
        """Get the pending task creation request without clearing it."""
        return self._pending_task_create

    def handle_hub_action(self, payload: dict[str, Any]) -> None:
        """
        Handle an incoming action from the hub.

        Called by the HubClient when an action message is received.

        Args:
            payload: The action payload from the hub.
        """
        try:
            action = PendingAction.from_dict(payload)

            # Handle RESPONSE action type specially
            if action.action_type == ActionType.RESPONSE:
                response = PendingResponse.from_action(action)
                self._pending_response = response

                # Notify response callbacks
                for callback in self._response_callbacks:
                    try:
                        callback(response)
                    except Exception:
                        pass
            elif action.action_type == ActionType.CREATE_TASK:
                task_create = PendingTaskCreate.from_action(action)
                self._pending_task_create = task_create

                # Notify task create callbacks
                for callback in self._task_create_callbacks:
                    try:
                        callback(task_create)
                    except Exception:
                        pass
            elif action.action_type == ActionType.FETCH_GITHUB_ISSUES:
                # Handle GitHub issues fetch request asynchronously
                import asyncio

                request_id = action.data.get("request_id")
                label = action.data.get("label", "galangal")
                asyncio.create_task(self._handle_fetch_github_issues(request_id, label))
            else:
                self._pending = action

                # Notify action callbacks
                for callback in self._callbacks:
                    try:
                        callback(action)
                    except Exception:
                        pass

        except (KeyError, ValueError) as e:
            # Invalid action payload - log and ignore
            import structlog

            logger = structlog.get_logger()
            logger.warning("invalid_hub_action", error=str(e), payload=payload)

    def on_action(self, callback: Callable[[PendingAction], None]) -> None:
        """
        Register a callback for when an action is received.

        The callback is called immediately when an action arrives,
        before the TUI polls for it.

        Args:
            callback: Function to call with the action.
        """
        self._callbacks.append(callback)

    def on_response(self, callback: Callable[[PendingResponse], None]) -> None:
        """
        Register a callback for when a response is received.

        The callback is called immediately when a response arrives,
        before the TUI polls for it.

        Args:
            callback: Function to call with the response.
        """
        self._response_callbacks.append(callback)

    def on_task_create(self, callback: Callable[[PendingTaskCreate], None]) -> None:
        """
        Register a callback for when a task creation request is received.

        The callback is called immediately when a request arrives,
        before the TUI polls for it.

        Args:
            callback: Function to call with the task create request.
        """
        self._task_create_callbacks.append(callback)

    def clear(self) -> None:
        """Clear any pending action, response, and task create request."""
        self._pending = None
        self._pending_response = None
        self._pending_task_create = None

    async def _handle_fetch_github_issues(
        self,
        request_id: str | None,
        label: str = "galangal",
    ) -> None:
        """
        Handle a request to fetch GitHub issues.

        Fetches issues with the given label and sends them back to the hub.

        Args:
            request_id: Request ID for correlating with the hub request.
            label: Label to filter issues by.
        """
        try:
            from galangal.github.issues import list_issues
            from galangal.hub.client import get_hub_client

            # Fetch issues from GitHub
            issues = list_issues(label=label)

            # Convert to dict format for sending
            issues_data = [
                {
                    "number": issue.number,
                    "title": issue.title,
                    "labels": issue.labels,
                    "state": issue.state,
                    "author": issue.author,
                }
                for issue in issues
            ]

            # Send back to hub
            client = get_hub_client()
            if client:
                await client.send_github_issues(issues_data, request_id)

        except Exception as e:
            import structlog

            logger = structlog.get_logger()
            logger.warning("fetch_github_issues_failed", error=str(e))


# Global action handler instance
_action_handler: ActionHandler | None = None


def get_action_handler() -> ActionHandler:
    """Get the global action handler instance."""
    global _action_handler
    if _action_handler is None:
        _action_handler = ActionHandler()
    return _action_handler


def set_action_handler(handler: ActionHandler | None) -> None:
    """Set the global action handler instance."""
    global _action_handler
    _action_handler = handler
