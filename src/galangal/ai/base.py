"""
Abstract base class for AI backends.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.config.schema import AIBackendConfig
    from galangal.ui.tui import StageUI

# Type alias for pause check callback
PauseCheck = Callable[[], bool]


class AIBackend(ABC):
    """Abstract base class for AI backends."""

    def __init__(self, config: Optional["AIBackendConfig"] = None):
        """
        Initialize the backend with optional configuration.

        Args:
            config: Backend-specific configuration from config.ai.backends.
                   If None, backend should use sensible defaults.
        """
        self._config = config

    @property
    def config(self) -> Optional["AIBackendConfig"]:
        """Return the backend configuration."""
        return self._config

    @property
    def read_only(self) -> bool:
        """Return whether this backend runs in read-only mode."""
        return self._config.read_only if self._config else False

    def _substitute_placeholders(self, args: list[str], **kwargs: str | int) -> list[str]:
        """
        Substitute placeholders in command arguments.

        Replaces {placeholder} patterns with provided values.

        Args:
            args: List of argument strings with optional placeholders
            **kwargs: Placeholder values (e.g., max_turns=200, schema_file="/tmp/s.json")

        Returns:
            List of arguments with placeholders replaced
        """
        result = []
        for arg in args:
            for key, value in kwargs.items():
                arg = arg.replace(f"{{{key}}}", str(value))
            result.append(arg)
        return result

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui: Optional["StageUI"] = None,
        pause_check: PauseCheck | None = None,
    ) -> StageResult:
        """
        Invoke the AI with a prompt for a full stage execution.

        Args:
            prompt: The full prompt to send
            timeout: Maximum time in seconds
            max_turns: Maximum conversation turns
            ui: Optional TUI for progress display
            pause_check: Optional callback that returns True if pause requested

        Returns:
            StageResult with success/failure and structured outcome type
        """
        pass

    @abstractmethod
    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """
        Simple text generation (for PR titles, commit messages, task names).

        Args:
            prompt: The prompt to send
            timeout: Maximum time in seconds

        Returns:
            Generated text, or empty string on failure
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the backend name."""
        pass
