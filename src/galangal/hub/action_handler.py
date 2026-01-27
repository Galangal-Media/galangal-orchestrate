"""
Handler for remote actions from hub.

Processes incoming action requests and coordinates with the TUI
to execute them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ActionType(str, Enum):
    """Types of actions that can be received from hub."""

    APPROVE = "approve"
    REJECT = "reject"
    SKIP = "skip"
    ROLLBACK = "rollback"
    INTERRUPT = "interrupt"


@dataclass
class PendingAction:
    """A pending action from the hub."""

    action_type: ActionType
    task_name: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PendingAction":
        """Create from dictionary (hub message payload)."""
        return cls(
            action_type=ActionType(d["action_type"]),
            task_name=d["task_name"],
            data=d.get("data", {}),
        )


class ActionHandler:
    """
    Handles incoming actions from the hub.

    The handler maintains a queue of pending actions that the TUI
    can poll and process during its normal operation.
    """

    def __init__(self) -> None:
        self._pending: PendingAction | None = None
        self._callbacks: list[Callable[[PendingAction], None]] = []

    @property
    def has_pending_action(self) -> bool:
        """Check if there is a pending action."""
        return self._pending is not None

    def get_pending_action(self) -> PendingAction | None:
        """Get and clear the pending action."""
        action = self._pending
        self._pending = None
        return action

    def peek_pending_action(self) -> PendingAction | None:
        """Get the pending action without clearing it."""
        return self._pending

    def handle_hub_action(self, payload: dict[str, Any]) -> None:
        """
        Handle an incoming action from the hub.

        Called by the HubClient when an action message is received.

        Args:
            payload: The action payload from the hub.
        """
        try:
            action = PendingAction.from_dict(payload)
            self._pending = action

            # Notify callbacks
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

    def clear(self) -> None:
        """Clear any pending action."""
        self._pending = None


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
