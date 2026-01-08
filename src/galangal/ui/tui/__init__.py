"""
Textual TUI for workflow execution display.

This package provides:
- WorkflowTUIApp: Main TUI application for workflow execution
- PromptType: Enum of prompt types the TUI can show
- StageUI: Interface for stage execution UI updates
- TUIAdapter: Adapter connecting ClaudeBackend to TUI
- run_stage_with_tui: Entry point for running a single stage with TUI
"""

from galangal.ui.tui.adapters import PromptType, StageUI, TUIAdapter
from galangal.ui.tui.app import StageTUIApp, WorkflowTUIApp
from galangal.ui.tui.entry import run_stage_with_tui
from galangal.ui.tui.modals import MultilineInputModal, PromptModal, PromptOption, TextInputModal
from galangal.ui.tui.types import (
    ActivityCategory,
    ActivityEntry,
    ActivityLevel,
    export_activity_log,
)
from galangal.ui.tui.widgets import (
    CurrentActionWidget,
    FilesPanelWidget,
    HeaderWidget,
    StageProgressWidget,
)

__all__ = [
    # Main app
    "WorkflowTUIApp",
    "StageTUIApp",
    # Adapters and interfaces
    "PromptType",
    "StageUI",
    "TUIAdapter",
    # Entry points
    "run_stage_with_tui",
    # Activity log types
    "ActivityEntry",
    "ActivityLevel",
    "ActivityCategory",
    "export_activity_log",
    # Widgets
    "HeaderWidget",
    "StageProgressWidget",
    "CurrentActionWidget",
    "FilesPanelWidget",
    # Modals
    "PromptOption",
    "PromptModal",
    "TextInputModal",
    "MultilineInputModal",
]
