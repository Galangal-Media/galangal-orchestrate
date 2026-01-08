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


def _init_logging() -> None:
    """Initialize structured logging from config."""
    from galangal.config.loader import get_config
    from galangal.logging import configure_logging

    config = get_config()
    log_config = config.logging

    if log_config.enabled:
        configure_logging(
            level=log_config.level,  # type: ignore
            log_file=log_config.file,
            json_format=log_config.json_format,
            console_output=log_config.console,
        )


def run_workflow(state: WorkflowState) -> None:
    """Run the workflow from current state to completion or failure."""
    from galangal.core.workflow.tui_runner import _run_workflow_with_tui
    from galangal.logging import workflow_logger

    # Initialize logging if configured
    _init_logging()

    # Log workflow start
    workflow_logger.workflow_started(
        task_name=state.task_name,
        task_type=state.task_type.value,
        stage=state.stage.value,
    )

    try:
        _run_workflow_with_tui(state)
    finally:
        # Log workflow end
        success = state.stage == state.__class__.__dict__.get("stage", state.stage)
        workflow_logger.workflow_completed(
            task_name=state.task_name,
            task_type=state.task_type.value,
            success=(state.stage.value == "COMPLETE"),
        )
