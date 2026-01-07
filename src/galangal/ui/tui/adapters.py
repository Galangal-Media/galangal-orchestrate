"""
UI adapters and interfaces for stage execution.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galangal.ui.tui.app import WorkflowTUIApp


class PromptType(Enum):
    """Types of prompts the TUI can show."""

    NONE = "none"
    PLAN_APPROVAL = "plan_approval"
    DESIGN_APPROVAL = "design_approval"
    COMPLETION = "completion"
    TEXT_INPUT = "text_input"
    PREFLIGHT_RETRY = "preflight_retry"
    STAGE_FAILURE = "stage_failure"
    POST_COMPLETION = "post_completion"
    TASK_TYPE = "task_type"


class StageUI:
    """Interface for stage execution UI updates."""

    def set_status(self, status: str, detail: str = "") -> None:
        pass

    def add_activity(self, activity: str, icon: str = "•") -> None:
        pass

    def add_raw_line(self, line: str) -> None:
        pass

    def set_turns(self, turns: int) -> None:
        pass

    def finish(self, success: bool) -> None:
        pass


class TUIAdapter(StageUI):
    """Adapter to connect ClaudeBackend to TUI."""

    def __init__(self, app: WorkflowTUIApp):
        self.app = app

    def set_status(self, status: str, detail: str = "") -> None:
        self.app.set_status(status, detail)

    def add_activity(self, activity: str, icon: str = "•") -> None:
        self.app.add_activity(activity, icon)

        # Track file operations
        if "Read:" in activity or "📖" in activity:
            path = activity.split(":")[-1].strip() if ":" in activity else activity
            self.app.add_file("read", path)
        elif "Edit:" in activity or "Write:" in activity or "✏️" in activity:
            path = activity.split(":")[-1].strip() if ":" in activity else activity
            self.app.add_file("write", path)

    def add_raw_line(self, line: str) -> None:
        """Pass raw line to app for storage and display."""
        self.app.add_raw_line(line)

    def set_turns(self, turns: int) -> None:
        self.app.set_turns(turns)

    def finish(self, success: bool) -> None:
        pass
