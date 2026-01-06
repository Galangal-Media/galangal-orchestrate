"""
Abstract base class for AI backends.
"""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI


class AIBackend(ABC):
    """Abstract base class for AI backends."""

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui: Optional["StageUI"] = None,
    ) -> tuple[bool, str]:
        """
        Invoke the AI with a prompt for a full stage execution.

        Args:
            prompt: The full prompt to send
            timeout: Maximum time in seconds
            max_turns: Maximum conversation turns
            ui: Optional TUI for progress display

        Returns:
            (success, output) tuple
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
