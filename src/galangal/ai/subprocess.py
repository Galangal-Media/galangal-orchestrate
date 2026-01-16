"""
Subprocess runner with pause/timeout handling for AI backends.
"""

from __future__ import annotations

import select
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from galangal.config.loader import get_project_root

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI


class RunOutcome(Enum):
    """Outcome of a subprocess run."""

    COMPLETED = "completed"
    PAUSED = "paused"
    TIMEOUT = "timeout"


@dataclass
class RunResult:
    """Result of running a subprocess."""

    outcome: RunOutcome
    exit_code: int | None
    output: str
    timeout_seconds: int | None = None

    @property
    def completed(self) -> bool:
        return self.outcome == RunOutcome.COMPLETED

    @property
    def paused(self) -> bool:
        return self.outcome == RunOutcome.PAUSED

    @property
    def timed_out(self) -> bool:
        return self.outcome == RunOutcome.TIMEOUT


# Type aliases
PauseCheck = Callable[[], bool]
OutputCallback = Callable[[str], None]
IdleCallback = Callable[[float], None]  # Called with elapsed seconds


class SubprocessRunner:
    """
    Manages subprocess lifecycle with pause/timeout support.

    Consolidates the common subprocess handling pattern used by AI backends:
    - Non-blocking output reading with select()
    - Pause request handling (graceful termination)
    - Timeout handling
    - Periodic idle callbacks for status updates

    Usage:
        runner = SubprocessRunner(
            command="cat prompt.txt | claude --verbose",
            timeout=3600,
            pause_check=lambda: user_requested_pause,
            on_output=lambda line: process_line(line),
            on_idle=lambda elapsed: update_status(elapsed),
        )
        result = runner.run()
        if result.completed:
            # Process result.output
    """

    def __init__(
        self,
        command: str,
        timeout: int = 14400,
        pause_check: PauseCheck | None = None,
        ui: StageUI | None = None,
        on_output: OutputCallback | None = None,
        on_idle: IdleCallback | None = None,
        idle_interval: float = 3.0,
        poll_interval_active: float = 0.05,
        poll_interval_idle: float = 0.5,
    ):
        """
        Initialize the subprocess runner.

        Args:
            command: Shell command to execute
            timeout: Maximum runtime in seconds
            pause_check: Callback returning True if pause requested
            ui: Optional TUI for basic status updates
            on_output: Callback for each output line
            on_idle: Callback when idle (no output), receives elapsed seconds
            idle_interval: Seconds between idle callbacks
            poll_interval_active: Sleep between polls when receiving output
            poll_interval_idle: Sleep between polls when idle
        """
        self.command = command
        self.timeout = timeout
        self.pause_check = pause_check
        self.ui = ui
        self.on_output = on_output
        self.on_idle = on_idle
        self.idle_interval = idle_interval
        self.poll_interval_active = poll_interval_active
        self.poll_interval_idle = poll_interval_idle

    def run(self) -> RunResult:
        """
        Run the subprocess with pause/timeout handling.

        Returns:
            RunResult with outcome, exit code, and captured output
        """
        process = subprocess.Popen(
            self.command,
            shell=True,
            cwd=get_project_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines: list[str] = []
        start_time = time.time()
        last_idle_callback = start_time

        try:
            while True:
                retcode = process.poll()

                # Read available output (non-blocking)
                had_output = self._read_output(process, output_lines)

                # Update last idle callback time if we had output
                if had_output:
                    last_idle_callback = time.time()

                # Process completed
                if retcode is not None:
                    break

                # Check for pause request
                if self.pause_check and self.pause_check():
                    self._terminate_gracefully(process)
                    if self.ui:
                        self.ui.add_activity("Paused by user request", "⏸️")
                    return RunResult(
                        outcome=RunOutcome.PAUSED,
                        exit_code=None,
                        output="".join(output_lines),
                    )

                # Check for timeout
                elapsed = time.time() - start_time
                if elapsed > self.timeout:
                    process.kill()
                    if self.ui:
                        self.ui.add_activity(f"Timeout after {self.timeout}s", "❌")
                    return RunResult(
                        outcome=RunOutcome.TIMEOUT,
                        exit_code=None,
                        output="".join(output_lines),
                        timeout_seconds=self.timeout,
                    )

                # Idle callback for status updates
                current_time = time.time()
                if self.on_idle and current_time - last_idle_callback >= self.idle_interval:
                    self.on_idle(elapsed)
                    last_idle_callback = current_time

                # Adaptive sleep
                time.sleep(self.poll_interval_active if had_output else self.poll_interval_idle)

            # Capture any remaining output
            remaining = self._capture_remaining(process)
            if remaining:
                output_lines.append(remaining)

            return RunResult(
                outcome=RunOutcome.COMPLETED,
                exit_code=process.returncode,
                output="".join(output_lines),
            )

        except Exception:
            # Ensure process is terminated on any error
            try:
                process.kill()
            except Exception:
                pass
            raise

    def _read_output(
        self,
        process: subprocess.Popen[str],
        output_lines: list[str],
    ) -> bool:
        """
        Read all available output lines (non-blocking).

        Returns True if any output was read.
        """
        had_output = False

        if not process.stdout:
            return False

        try:
            while True:
                ready, _, _ = select.select([process.stdout], [], [], 0)
                if not ready:
                    break

                line = process.stdout.readline()
                if not line:
                    break

                output_lines.append(line)
                had_output = True

                if self.on_output:
                    self.on_output(line)

        except (ValueError, TypeError, OSError):
            # select() may fail on non-selectable streams
            pass

        return had_output

    def _terminate_gracefully(self, process: subprocess.Popen[str]) -> None:
        """Terminate process gracefully, then force kill if needed."""
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def _capture_remaining(self, process: subprocess.Popen[str]) -> str:
        """Capture any remaining output after process completes."""
        try:
            remaining, _ = process.communicate(timeout=10)
            return remaining or ""
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return ""
