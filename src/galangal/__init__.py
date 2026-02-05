"""
Galangal Orchestrate - AI-driven development workflow orchestrator.

A deterministic workflow system that guides AI assistants through
structured development stages: PM -> DESIGN -> DEV -> TEST -> QA -> REVIEW -> DOCS.
"""

from pathlib import Path

from galangal.exceptions import (
    AIError,
    ConfigError,
    ExitCode,
    GalangalError,
    TaskError,
    ValidationError,
    WorkflowError,
)
from galangal.logging import (
    WorkflowLogger,
    configure_logging,
    get_logger,
    workflow_logger,
)


def _read_version() -> str:
    """Read version from package metadata or VERSION file."""
    # First, try to read from installed package metadata (works after pip install)
    try:
        from importlib.metadata import version

        return version("galangal-orchestrate")
    except Exception:
        pass

    # Fallback: try VERSION file (for development mode)
    locations = [
        Path(__file__).parent.parent.parent / "VERSION",  # src/../VERSION (dev)
    ]
    for path in locations:
        if path.exists():
            return path.read_text().strip()

    return "0.0.0"


__version__ = _read_version()

__all__ = [
    # Exceptions
    "GalangalError",
    "ConfigError",
    "ValidationError",
    "WorkflowError",
    "TaskError",
    "AIError",
    "ExitCode",
    # Logging
    "configure_logging",
    "get_logger",
    "WorkflowLogger",
    "workflow_logger",
]
