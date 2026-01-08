"""
UI adapters and interfaces for stage execution.

This module provides:
- PromptType: Enum for different prompt contexts
- PROMPT_OPTIONS: Registry mapping PromptType to available options
- StageUI: Interface for stage execution UI updates
- TUIAdapter: Adapter connecting ClaudeBackend to WorkflowTUIApp
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from galangal.ui.tui.modals import PromptOption

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


# Default options for prompts without specific configuration
DEFAULT_PROMPT_OPTIONS: list[PromptOption] = [
    PromptOption("1", "Yes", "yes", "#b8bb26"),
    PromptOption("2", "No", "no", "#fb4934"),
    PromptOption("3", "Quit", "quit", "#fabd2f"),
]

# Registry mapping PromptType to available options
# This centralizes prompt configuration and makes it easy to add new prompt types
PROMPT_OPTIONS: dict[PromptType, list[PromptOption]] = {
    PromptType.PLAN_APPROVAL: [
        PromptOption("1", "Approve", "yes", "#b8bb26"),
        PromptOption("2", "Reject", "no", "#fb4934"),
        PromptOption("3", "Quit", "quit", "#fabd2f"),
    ],
    PromptType.DESIGN_APPROVAL: [
        PromptOption("1", "Approve", "yes", "#b8bb26"),
        PromptOption("2", "Reject", "no", "#fb4934"),
        PromptOption("3", "Quit", "quit", "#fabd2f"),
    ],
    PromptType.COMPLETION: [
        PromptOption("1", "Create PR", "yes", "#b8bb26"),
        PromptOption("2", "Back to DEV", "no", "#fb4934"),
        PromptOption("3", "Quit", "quit", "#fabd2f"),
    ],
    PromptType.PREFLIGHT_RETRY: [
        PromptOption("1", "Retry", "retry", "#b8bb26"),
        PromptOption("2", "Quit", "quit", "#fb4934"),
    ],
    PromptType.STAGE_FAILURE: [
        PromptOption("1", "Retry", "retry", "#b8bb26"),
        PromptOption("2", "Fix in DEV", "fix_in_dev", "#fabd2f"),
        PromptOption("3", "Quit", "quit", "#fb4934"),
    ],
    PromptType.POST_COMPLETION: [
        PromptOption("1", "New Task", "new_task", "#b8bb26"),
        PromptOption("2", "Quit", "quit", "#fabd2f"),
    ],
    PromptType.TASK_TYPE: [
        PromptOption("1", "Feature - New functionality", "feature", "#b8bb26"),
        PromptOption("2", "Bug Fix - Fix broken behavior", "bugfix", "#fb4934"),
        PromptOption("3", "Refactor - Restructure code", "refactor", "#83a598"),
        PromptOption("4", "Chore - Dependencies, config", "chore", "#fabd2f"),
        PromptOption("5", "Docs - Documentation only", "docs", "#d3869b"),
        PromptOption("6", "Hotfix - Critical fix", "hotfix", "#fe8019"),
    ],
}


def get_prompt_options(prompt_type: PromptType) -> list[PromptOption]:
    """
    Get the options for a given prompt type.

    Args:
        prompt_type: The type of prompt to get options for.

    Returns:
        List of PromptOption objects for the prompt type.
        Falls back to DEFAULT_PROMPT_OPTIONS if type not in registry.
    """
    return PROMPT_OPTIONS.get(prompt_type, DEFAULT_PROMPT_OPTIONS)


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
