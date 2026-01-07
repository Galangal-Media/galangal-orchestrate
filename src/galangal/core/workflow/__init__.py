"""
Workflow execution - stage execution, rollback, loop handling.

This package provides:
- run_workflow: Main entry point for workflow execution
- get_next_stage: Get the next stage in the workflow
- execute_stage: Execute a single stage
- handle_rollback: Handle rollback signals from validators
"""

import os

from rich.console import Console

from galangal.core.state import WorkflowState
from galangal.core.workflow.core import (
    archive_rollback_if_exists,
    execute_stage,
    get_next_stage,
    handle_rollback,
)

console = Console()

__all__ = [
    "run_workflow",
    "get_next_stage",
    "execute_stage",
    "handle_rollback",
    "archive_rollback_if_exists",
]


def run_workflow(state: WorkflowState) -> None:
    """Run the workflow from current state to completion or failure."""
    # Try persistent TUI first (unless disabled)
    if not os.environ.get("GALANGAL_NO_TUI"):
        try:
            from galangal.core.workflow.tui_runner import _run_workflow_with_tui

            result = _run_workflow_with_tui(state)
            if result != "use_legacy":
                # TUI handled the workflow
                return
        except Exception as e:
            console.print(f"[yellow]TUI error: {e}. Using legacy mode.[/yellow]")

    # Legacy mode (no persistent TUI)
    from galangal.core.workflow.legacy_runner import _run_workflow_legacy

    _run_workflow_legacy(state)
