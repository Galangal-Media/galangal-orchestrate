"""
Custom exceptions for Galangal Orchestrate.

All galangal-specific exceptions inherit from GalangalError,
making it easy to catch all galangal errors in one place.

Exit codes are defined for consistent scripting/automation support.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """
    Standard exit codes for CLI commands.

    Use these for consistent exit codes across all commands,
    enabling reliable scripting and automation.

    Exit code ranges:
    - 0: Success
    - 1-9: General errors
    - 10-19: Configuration errors
    - 20-29: Task errors
    - 30-39: Workflow errors
    - 40-49: Validation errors
    - 50-59: AI/Backend errors
    - 60-69: GitHub errors
    """

    # Success
    SUCCESS = 0

    # General errors (1-9)
    ERROR = 1  # Generic error
    NOT_INITIALIZED = 2  # Galangal not initialized in project
    INTERRUPTED = 3  # User interrupted (Ctrl+C)

    # Configuration errors (10-19)
    CONFIG_INVALID = 10  # Invalid configuration
    CONFIG_NOT_FOUND = 11  # Config file not found
    CONFIG_PARSE_ERROR = 12  # YAML/JSON parse error

    # Task errors (20-29)
    TASK_NOT_FOUND = 20  # Task doesn't exist
    TASK_EXISTS = 21  # Task already exists
    TASK_ACTIVE = 22  # Task is currently active
    NO_ACTIVE_TASK = 23  # No active task

    # Workflow errors (30-39)
    WORKFLOW_FAILED = 30  # Workflow execution failed
    STAGE_FAILED = 31  # Stage execution failed
    MAX_RETRIES = 32  # Max retries exceeded
    ROLLBACK_BLOCKED = 33  # Rollback was blocked

    # Validation errors (40-49)
    VALIDATION_FAILED = 40  # Validation command failed
    PREFLIGHT_FAILED = 41  # Preflight check failed

    # AI/Backend errors (50-59)
    AI_ERROR = 50  # General AI backend error
    AI_AUTH = 51  # Authentication error
    AI_TIMEOUT = 52  # AI operation timed out
    AI_RATE_LIMIT = 53  # Rate limited
    AI_NOT_FOUND = 54  # AI CLI not found

    # GitHub errors (60-69)
    GITHUB_ERROR = 60  # General GitHub error
    GITHUB_AUTH = 61  # GitHub authentication error
    GITHUB_NOT_FOUND = 62  # GitHub CLI not found


class GalangalError(Exception):
    """
    Base exception for all Galangal errors.

    Attributes:
        exit_code: Suggested exit code for CLI commands.
        message: Human-readable error message.
    """

    exit_code: ExitCode = ExitCode.ERROR

    def __init__(self, message: str, exit_code: ExitCode | None = None):
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class ConfigError(GalangalError):
    """Raised when configuration is invalid or cannot be loaded."""

    exit_code = ExitCode.CONFIG_INVALID


class ValidationError(GalangalError):
    """Raised when stage validation fails."""

    exit_code = ExitCode.VALIDATION_FAILED


class WorkflowError(GalangalError):
    """Raised when workflow execution encounters an error."""

    exit_code = ExitCode.WORKFLOW_FAILED


class TaskError(GalangalError):
    """Raised when task operations fail (create, switch, etc.)."""

    exit_code = ExitCode.TASK_NOT_FOUND


class AIError(GalangalError):
    """Raised when AI backend operations fail."""

    exit_code = ExitCode.AI_ERROR
