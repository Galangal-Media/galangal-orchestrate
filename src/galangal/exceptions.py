"""
Custom exceptions for Galangal Orchestrate.

All galangal-specific exceptions inherit from GalangalError,
making it easy to catch all galangal errors in one place.
"""


class GalangalError(Exception):
    """Base exception for all Galangal errors."""

    pass


class ConfigError(GalangalError):
    """Raised when configuration is invalid or cannot be loaded."""

    pass


class ValidationError(GalangalError):
    """Raised when stage validation fails."""

    pass


class WorkflowError(GalangalError):
    """Raised when workflow execution encounters an error."""

    pass


class TaskError(GalangalError):
    """Raised when task operations fail (create, switch, etc.)."""

    pass
