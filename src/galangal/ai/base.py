"""
Abstract base class for AI backends.
"""

from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.ai.subprocess import SubprocessResult
    from galangal.config.schema import AIBackendConfig
    from galangal.ui.tui import StageUI

# Type alias for pause check callback
PauseCheck = Callable[[], bool]


class AIBackend(ABC):
    """Abstract base class for AI backends."""

    def __init__(self, config: AIBackendConfig | None = None):
        """
        Initialize the backend with optional configuration.

        Args:
            config: Backend-specific configuration from config.ai.backends.
                   If None, backend should use sensible defaults.
        """
        self._config = config

    @property
    def config(self) -> AIBackendConfig | None:
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

    def _resolve_command_and_args(self, max_turns: int) -> tuple[str, list[str]]:
        """
        Resolve the command and args from config or defaults.

        Args:
            max_turns: Maximum conversation turns for placeholder substitution.

        Returns:
            Tuple of (command, substituted_args).
        """
        if self._config:
            command = self._config.command
            args = self._substitute_placeholders(self._config.args, max_turns=max_turns)
        else:
            command = self.DEFAULT_COMMAND
            args = self._substitute_placeholders(self.DEFAULT_ARGS, max_turns=max_turns)
        return command, args

    def _handle_subprocess_result(
        self, result: SubprocessResult, ui: StageUI | None, timeout: int
    ) -> StageResult | None:
        """
        Handle common subprocess exit conditions (paused, timed out).

        Returns a StageResult if the condition was handled, or None to continue processing.
        """
        if result.paused:
            if ui:
                ui.finish(success=False)
            return StageResult.paused()

        if result.timed_out:
            return StageResult.timeout(result.timeout_seconds or timeout)

        return None

    @staticmethod
    def _format_elapsed(elapsed: float) -> str:
        """Format elapsed seconds into a human-readable string."""
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        return f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    @staticmethod
    def _notify_hub_output(line: str) -> None:
        """Stream a line to hub for remote monitoring. Non-critical."""
        try:
            from galangal.hub.hooks import notify_output
            notify_output(line, "raw")
        except Exception:
            pass

    @contextmanager
    def _temp_file(
        self,
        content: str | None = None,
        suffix: str = ".txt",
    ) -> Generator[str, None, None]:
        """
        Context manager for temporary file creation with automatic cleanup.

        Creates a temporary file, optionally writes content to it, yields the path,
        and ensures cleanup on exit (even if an exception occurs).

        Args:
            content: Optional content to write to the file. If None, creates an
                    empty file (useful for output files written by external processes).
            suffix: File suffix (default: ".txt")

        Yields:
            Path to the temporary file

        Example:
            with self._temp_file(prompt, suffix=".txt") as prompt_file:
                shell_cmd = f"cat '{prompt_file}' | claude ..."
                # File is automatically cleaned up after the block
        """
        filepath: str | None = None
        try:
            if content is not None:
                # Create file with content
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=suffix, delete=False, encoding="utf-8"
                ) as f:
                    f.write(content)
                    filepath = f.name
            else:
                # Create empty file for external process to write
                fd, filepath = tempfile.mkstemp(suffix=suffix)
                os.close(fd)
            yield filepath
        finally:
            if filepath and os.path.exists(filepath):
                try:
                    os.unlink(filepath)
                except OSError:
                    pass

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui: StageUI | None = None,
        pause_check: PauseCheck | None = None,
        stage: str | None = None,
        log_file: str | None = None,
    ) -> StageResult:
        """
        Invoke the AI with a prompt for a full stage execution.

        Args:
            prompt: The full prompt to send
            timeout: Maximum time in seconds
            max_turns: Maximum conversation turns
            ui: Optional TUI for progress display
            pause_check: Optional callback that returns True if pause requested
            stage: Optional stage name for backends that customize behavior per stage
            log_file: Optional path to log file for streaming output

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
