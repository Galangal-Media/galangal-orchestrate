"""
Structured logging for Galangal workflow execution.

Provides JSON-formatted logging for stage execution, validation results,
and workflow events. Supports both console and file output.

Usage:
    from galangal.logging import get_logger, configure_logging

    # Configure at startup
    configure_logging(level="info", log_file="logs/galangal.jsonl")

    # Get a logger
    logger = get_logger(__name__)
    logger.info("stage_started", stage="DEV", task="my-task")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog
from structlog.types import Processor

if TYPE_CHECKING:
    from galangal.core.state import Stage, TaskType, WorkflowState


LogLevel = Literal["debug", "info", "warning", "error"]


def _add_log_level(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    """Add log level to event dict for JSON output."""
    if method_name == "warn":
        method_name = "warning"
    event_dict["level"] = method_name.upper()
    return event_dict


def get_processors(json_format: bool = True) -> list[Processor]:
    """
    Get structlog processors for the configured format.

    Args:
        json_format: If True, output JSON. If False, output pretty console format.

    Returns:
        List of structlog processors.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        return [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        return [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]


def configure_logging(
    level: LogLevel = "info",
    log_file: str | Path | None = None,
    json_format: bool = True,
    console_output: bool = True,
) -> None:
    """
    Configure structured logging for Galangal.

    Should be called once at application startup before any logging occurs.

    Args:
        level: Minimum log level (debug, info, warning, error).
        log_file: Optional path to write JSON logs to.
        json_format: If True, output JSON format. If False, pretty console format.
        console_output: If True, also output to console (stderr).

    Example:
        >>> configure_logging(level="info", log_file="logs/galangal.jsonl")
        >>> logger = get_logger(__name__)
        >>> logger.info("workflow_started", task="my-task")
    """
    log_level = getattr(logging, level.upper())

    # Configure standard library logging
    handlers: list[logging.Handler] = []

    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        handlers.append(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=handlers,
        force=True,
    )

    # Configure structlog
    structlog.configure(
        processors=get_processors(json_format),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__).

    Returns:
        A structlog BoundLogger instance.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("stage_completed", stage="DEV", duration=45.2)
    """
    return structlog.get_logger(name)


# Convenience function to bind context for a task
def bind_task_context(task_name: str, task_type: str) -> None:
    """
    Bind task context to all subsequent log messages.

    Args:
        task_name: Name of the current task.
        task_type: Type of the task (feature, bug_fix, etc.).
    """
    structlog.contextvars.bind_contextvars(
        task=task_name,
        task_type=task_type,
    )


def clear_task_context() -> None:
    """Clear bound task context."""
    structlog.contextvars.unbind_contextvars("task", "task_type")


# Pre-defined event helpers for common workflow events
class WorkflowLogger:
    """
    Helper class for logging workflow events with consistent structure.

    Provides methods for logging common workflow events like stage starts,
    completions, failures, and retries.

    Example:
        >>> wf_logger = WorkflowLogger()
        >>> wf_logger.stage_started("DEV", "my-task", attempt=1)
        >>> wf_logger.stage_completed("DEV", "my-task", success=True, duration=120.5)
    """

    def __init__(self, logger: structlog.stdlib.BoundLogger | None = None):
        self._logger = logger or get_logger("galangal.workflow")

    def workflow_started(self, task_name: str, task_type: str, stage: str) -> None:
        """Log workflow start."""
        self._logger.info(
            "workflow_started",
            task=task_name,
            task_type=task_type,
            initial_stage=stage,
        )

    def workflow_completed(self, task_name: str, task_type: str, success: bool) -> None:
        """Log workflow completion."""
        self._logger.info(
            "workflow_completed",
            task=task_name,
            task_type=task_type,
            success=success,
        )

    def stage_started(
        self,
        stage: str,
        task_name: str,
        attempt: int = 1,
        max_retries: int = 5,
    ) -> None:
        """Log stage start."""
        self._logger.info(
            "stage_started",
            stage=stage,
            task=task_name,
            attempt=attempt,
            max_retries=max_retries,
        )

    def stage_completed(
        self,
        stage: str,
        task_name: str,
        success: bool,
        duration: float | None = None,
        output: str | None = None,
    ) -> None:
        """Log stage completion."""
        self._logger.info(
            "stage_completed",
            stage=stage,
            task=task_name,
            success=success,
            duration_seconds=duration,
        )

    def stage_failed(
        self,
        stage: str,
        task_name: str,
        error: str,
        attempt: int = 1,
    ) -> None:
        """Log stage failure."""
        self._logger.warning(
            "stage_failed",
            stage=stage,
            task=task_name,
            error=error,
            attempt=attempt,
        )

    def stage_retry(
        self,
        stage: str,
        task_name: str,
        attempt: int,
        reason: str,
    ) -> None:
        """Log stage retry."""
        self._logger.info(
            "stage_retry",
            stage=stage,
            task=task_name,
            attempt=attempt,
            reason=reason,
        )

    def validation_result(
        self,
        stage: str,
        task_name: str,
        success: bool,
        message: str,
        skipped: bool = False,
    ) -> None:
        """Log validation result."""
        self._logger.info(
            "validation_result",
            stage=stage,
            task=task_name,
            success=success,
            skipped=skipped,
            message=message,
        )

    def rollback(
        self,
        from_stage: str,
        to_stage: str,
        task_name: str,
        reason: str,
    ) -> None:
        """Log rollback event."""
        self._logger.warning(
            "rollback",
            from_stage=from_stage,
            to_stage=to_stage,
            task=task_name,
            reason=reason,
        )

    def approval_requested(
        self,
        stage: str,
        task_name: str,
        artifact: str,
    ) -> None:
        """Log approval request."""
        self._logger.info(
            "approval_requested",
            stage=stage,
            task=task_name,
            artifact=artifact,
        )

    def approval_result(
        self,
        stage: str,
        task_name: str,
        approved: bool,
        feedback: str | None = None,
    ) -> None:
        """Log approval result."""
        self._logger.info(
            "approval_result",
            stage=stage,
            task=task_name,
            approved=approved,
            feedback=feedback,
        )


# Global workflow logger instance
workflow_logger = WorkflowLogger()
