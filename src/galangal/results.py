"""
Structured result types for operations and stage execution.

This module provides type-safe result objects instead of tuple[bool, str]
with magic string prefixes like "PREFLIGHT_FAILED:" or "ROLLBACK:".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galangal.core.state import Stage


class StageResultType(Enum):
    """Types of outcomes from stage execution."""

    SUCCESS = auto()
    PREFLIGHT_FAILED = auto()
    VALIDATION_FAILED = auto()
    ROLLBACK_REQUIRED = auto()
    CLARIFICATION_NEEDED = auto()
    PAUSED = auto()
    TIMEOUT = auto()
    MAX_TURNS = auto()
    ERROR = auto()


@dataclass
class Result:
    """Base result for simple operations."""

    success: bool
    message: str

    def __bool__(self) -> bool:
        """Allow using result directly in boolean context."""
        return self.success


@dataclass
class StageResult(Result):
    """Result from stage execution with structured outcome type.

    Replaces the old pattern of encoding state in message strings like:
    - "PREFLIGHT_FAILED:details"
    - "ROLLBACK:DEV:reason"

    Now the type field explicitly indicates the outcome, and structured
    fields hold the relevant data.
    """

    type: StageResultType = StageResultType.SUCCESS
    rollback_to: Stage | None = None
    output: str | None = None

    @classmethod
    def success(cls, message: str = "", output: str | None = None) -> StageResult:
        """Create a successful stage result."""
        return cls(
            success=True,
            message=message,
            type=StageResultType.SUCCESS,
            output=output,
        )

    @classmethod
    def preflight_failed(cls, message: str, details: str = "") -> StageResult:
        """Create a preflight failure result."""
        return cls(
            success=False,
            message=message,
            type=StageResultType.PREFLIGHT_FAILED,
            output=details,
        )

    @classmethod
    def validation_failed(cls, message: str) -> StageResult:
        """Create a validation failure result."""
        return cls(
            success=False,
            message=message,
            type=StageResultType.VALIDATION_FAILED,
        )

    @classmethod
    def rollback_required(
        cls, message: str, rollback_to: Stage, output: str | None = None
    ) -> StageResult:
        """Create a rollback required result."""
        return cls(
            success=False,
            message=message,
            type=StageResultType.ROLLBACK_REQUIRED,
            rollback_to=rollback_to,
            output=output,
        )

    @classmethod
    def clarification_needed(cls, message: str = "") -> StageResult:
        """Create a clarification needed result."""
        return cls(
            success=False,
            message=message or "Clarification required. Please provide ANSWERS.md.",
            type=StageResultType.CLARIFICATION_NEEDED,
        )

    @classmethod
    def paused(cls, message: str = "User requested pause") -> StageResult:
        """Create a paused result."""
        return cls(
            success=False,
            message=message,
            type=StageResultType.PAUSED,
        )

    @classmethod
    def timeout(cls, timeout_seconds: int) -> StageResult:
        """Create a timeout result."""
        return cls(
            success=False,
            message=f"Timed out after {timeout_seconds}s",
            type=StageResultType.TIMEOUT,
        )

    @classmethod
    def max_turns(cls, output: str = "") -> StageResult:
        """Create a max turns exceeded result."""
        return cls(
            success=False,
            message="Max turns exceeded",
            type=StageResultType.MAX_TURNS,
            output=output,
        )

    @classmethod
    def error(cls, message: str, output: str | None = None) -> StageResult:
        """Create a general error result."""
        return cls(
            success=False,
            message=message,
            type=StageResultType.ERROR,
            output=output,
        )
