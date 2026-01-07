"""
Workflow execution - stage execution, rollback, loop handling.

This package provides:
- run_workflow: Main entry point for workflow execution
- get_next_stage: Get the next stage in the workflow
- execute_stage: Execute a single stage
- handle_rollback: Handle rollback signals from validators
"""

from galangal.core.state import WorkflowState
from galangal.core.workflow.core import (
    archive_rollback_if_exists,
    execute_stage,
    get_next_stage,
    handle_rollback,
)

__all__ = [
    "run_workflow",
    "get_next_stage",
    "execute_stage",
    "handle_rollback",
    "archive_rollback_if_exists",
]


def run_workflow(state: WorkflowState) -> None:
    """Run the workflow from current state to completion or failure."""
    from galangal.core.workflow.tui_runner import _run_workflow_with_tui

    _run_workflow_with_tui(state)
