"""
Subprocess runner with pause/timeout handling for AI backends.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import time
from collections import deque
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
        max_output_chars: int | None = 1_000_000,
        output_file: str | None = None,
        no_progress_timeout: int = 0,
        watchdog_suppressed: Callable[[], bool] | None = None,
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
            max_output_chars: Max output chars kept in memory (None for unlimited)
            output_file: Optional file path to stream full output
            no_progress_timeout: Kill the process if it emits no output for this
                many seconds (0 disables). Catches a wedged agent before the full
                timeout elapses.
            watchdog_suppressed: Optional callback; while it returns True the
                no-progress watchdog is held off (e.g. during a rate-limit wait
                when the CLI is legitimately idle).
        """
        self.command = command
        self.timeout = timeout
        self.no_progress_timeout = no_progress_timeout
        self.watchdog_suppressed = watchdog_suppressed
        self.pause_check = pause_check
        self.ui = ui
        self.on_output = on_output
        self.on_idle = on_idle
        self.idle_interval = idle_interval
        self.poll_interval_active = poll_interval_active
        self.poll_interval_idle = poll_interval_idle
        self.max_output_chars = max_output_chars
        self.output_file = output_file

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
            # Own process group so kill reaches the whole pipeline (the shell AND
            # the agent/test child it spawns). Without this, killing the shell on
            # timeout/watchdog leaves the child alive, holding the stdout pipe and
            # hanging the read of remaining output.
            start_new_session=True,
        )

        output_buffer: deque[str] = deque()
        output_chars = 0
        output_handle = None
        start_time = time.time()
        last_idle_callback = start_time
        # Distinct from last_idle_callback (which the idle tick also resets): this
        # only advances on real output, so the watchdog measures true silence.
        last_output_time = start_time

        if self.output_file:
            try:
                output_handle = open(self.output_file, "a", encoding="utf-8", buffering=1)
            except OSError:
                output_handle = None

        def record_output(chunk: str) -> None:
            nonlocal output_chars, output_handle
            if output_handle:
                try:
                    output_handle.write(chunk)
                except OSError:
                    output_handle = None

            output_buffer.append(chunk)
            output_chars += len(chunk)
            if self.max_output_chars is not None:
                while output_chars > self.max_output_chars and output_buffer:
                    removed = output_buffer.popleft()
                    output_chars -= len(removed)

        try:
            while True:
                retcode = process.poll()

                # Read available output (non-blocking)
                had_output = self._read_output(process, record_output)

                # Update last idle callback time if we had output
                if had_output:
                    now = time.time()
                    last_idle_callback = now
                    last_output_time = now

                # Process completed
                if retcode is not None:
                    break

                # Check for pause request
                if self.pause_check and self.pause_check():
                    self._terminate_gracefully(process)
                    self._capture_remaining(process, record_output)
                    if self.ui:
                        self.ui.add_activity("Paused by user request", "⏸️")
                    return RunResult(
                        outcome=RunOutcome.PAUSED,
                        exit_code=None,
                        output="".join(output_buffer),
                    )

                # While suppressed (e.g. a rate-limit wait), keep the watchdog
                # clock reset so a legitimately-idle CLI is never killed.
                if self.watchdog_suppressed and self.watchdog_suppressed():
                    last_output_time = time.time()

                # No-progress watchdog: kill a process that has gone silent for
                # too long even though the overall timeout hasn't elapsed.
                if (
                    self.no_progress_timeout
                    and time.time() - last_output_time > self.no_progress_timeout
                ):
                    self._kill_group(process)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    self._capture_remaining(process, record_output)
                    if self.ui:
                        self.ui.add_activity(
                            f"No output for {self.no_progress_timeout}s - aborting", "❌"
                        )
                    return RunResult(
                        outcome=RunOutcome.TIMEOUT,
                        exit_code=None,
                        output="".join(output_buffer),
                        timeout_seconds=self.no_progress_timeout,
                    )

                # Check for timeout
                elapsed = time.time() - start_time
                if elapsed > self.timeout:
                    self._kill_group(process)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    self._capture_remaining(process, record_output)
                    if self.ui:
                        self.ui.add_activity(f"Timeout after {self.timeout}s", "❌")
                    return RunResult(
                        outcome=RunOutcome.TIMEOUT,
                        exit_code=None,
                        output="".join(output_buffer),
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
            self._capture_remaining(process, record_output)

            return RunResult(
                outcome=RunOutcome.COMPLETED,
                exit_code=process.returncode,
                output="".join(output_buffer),
            )

        except Exception:
            # Ensure process is terminated on any error
            try:
                self._kill_group(process)
                process.wait(timeout=5)
            except Exception:
                pass
            raise
        finally:
            if output_handle:
                try:
                    output_handle.close()
                except OSError:
                    pass

    @staticmethod
    def _kill_group(process: subprocess.Popen[str]) -> None:
        """Kill the process's whole group so shell children die with it.

        ``process.kill()`` only signals the direct child (``/bin/sh``); the agent
        or test runner it spawned would otherwise survive and keep the pipe open.
        Falls back to a plain kill if the group signal can't be sent.

        Safety: only ever ``killpg`` a real, positive child pid whose group id is
        positive. A ``MagicMock`` process (in tests) has a ``pid`` that coerces to
        0 via ``__index__``; ``os.getpgid(0)``/``killpg(0, ...)`` would target the
        CALLER's own process group and SIGKILL the whole test session. Guard hard
        against that.
        """
        pid = getattr(process, "pid", None)
        if type(pid) is not int or pid <= 0:
            # Mocked or invalid process: never risk a group signal.
            try:
                process.kill()
            except Exception:
                pass
            return
        try:
            pgid = os.getpgid(pid)
            if pgid <= 0:
                raise OSError("refusing to signal process group <= 0")
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass

    def _read_output(
        self,
        process: subprocess.Popen[str],
        record_output: Callable[[str], None],
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

                record_output(line)
                had_output = True

                if self.on_output:
                    self.on_output(line)

        except (ValueError, TypeError, OSError):
            # select() may fail on non-selectable streams
            pass

        return had_output

    def _terminate_gracefully(self, process: subprocess.Popen[str]) -> None:
        """Terminate process gracefully, then force-kill the group if needed."""
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_group(process)

    def _capture_remaining(
        self,
        process: subprocess.Popen[str],
        record_output: Callable[[str], None],
    ) -> None:
        """Capture any remaining output after process completes."""
        try:
            remaining, _ = process.communicate(timeout=10)
            if remaining:
                record_output(remaining)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
