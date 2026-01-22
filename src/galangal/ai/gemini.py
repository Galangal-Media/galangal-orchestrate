"""
Gemini CLI backend implementation.

Supports the Gemini CLI tool for AI-driven development workflows.
Can be used as a cost-effective alternative for certain stages.

See: https://cloud.google.com/sdk/gcloud/reference/ai/gemini
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from galangal.ai.base import AIBackend, PauseCheck
from galangal.ai.errors import analyze_error
from galangal.ai.subprocess import SubprocessRunner
from galangal.config.loader import get_project_root
from galangal.logging import get_logger
from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI

logger = get_logger(__name__)


class GeminiBackend(AIBackend):
    """
    Gemini CLI backend.

    Uses the Gemini CLI tool to execute prompts. Can be configured
    as a cost-effective alternative for certain stages like DOCS or QA.

    Configuration example:
        ai:
          backends:
            gemini:
              command: gemini
              args:
                - "--output-format"
                - "stream-json"
                - "--max-tokens"
                - "{max_turns}"
              max_turns: 8192

          stage_backends:
            DOCS: gemini
            QA: gemini
    """

    # Default command and args when no config provided
    DEFAULT_COMMAND = "gemini"
    DEFAULT_ARGS = [
        "--output-format",
        "stream-json",
        "--max-tokens",
        "{max_turns}",
    ]

    @property
    def name(self) -> str:
        return "gemini"

    def _build_command(self, prompt_file: str, max_turns: int) -> str:
        """
        Build the shell command to invoke Gemini.

        Uses config.command and config.args if available, otherwise falls back
        to hard-coded defaults for backwards compatibility.

        Args:
            prompt_file: Path to temp file containing the prompt
            max_turns: Maximum output tokens (repurposed from max_turns)

        Returns:
            Shell command string ready for subprocess
        """
        if self._config:
            command = self._config.command
            args = self._substitute_placeholders(
                self._config.args,
                max_turns=max_turns,
            )
        else:
            # Backwards compatibility: use defaults
            command = self.DEFAULT_COMMAND
            args = self._substitute_placeholders(
                self.DEFAULT_ARGS,
                max_turns=max_turns,
            )

        args_str = " ".join(args)
        return f"cat '{prompt_file}' | {command} {args_str}"

    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 8192,
        ui: StageUI | None = None,
        pause_check: PauseCheck | None = None,
        stage: str | None = None,
        log_file: str | None = None,
    ) -> StageResult:
        """
        Invoke Gemini with a prompt.

        Args:
            prompt: The full prompt to send
            timeout: Maximum time in seconds
            max_turns: Maximum output tokens (Gemini uses this for token limit)
            ui: Optional TUI for progress display
            pause_check: Optional callback for pause detection
            stage: Optional stage name for logging
            log_file: Optional path to log file for streaming output

        Returns:
            StageResult with success/failure and output
        """
        # Track output for result processing
        full_output_lines: list[str] = []

        def on_output(line: str) -> None:
            """Process each output line."""
            full_output_lines.append(line)
            if ui:
                ui.add_raw_line(line)
            self._process_stream_line(line, ui)

        def on_idle(elapsed: float) -> None:
            """Update status when idle."""
            if ui:
                minutes = int(elapsed // 60)
                seconds = int(elapsed % 60)
                time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
                ui.set_status("waiting", f"Gemini ({time_str})")

        try:
            with self._temp_file(prompt, suffix=".txt") as prompt_file:
                shell_cmd = self._build_command(prompt_file, max_turns)

                if ui:
                    ui.set_status("starting", "initializing Gemini")
                    ui.add_activity("Gemini started", "🌟")

                runner = SubprocessRunner(
                    command=shell_cmd,
                    timeout=timeout,
                    pause_check=pause_check,
                    ui=ui,
                    on_output=on_output,
                    on_idle=on_idle,
                    idle_interval=5.0,
                    poll_interval_active=0.05,
                    poll_interval_idle=0.5,
                    output_file=log_file,
                )

                result = runner.run()

                if result.paused:
                    if ui:
                        ui.finish(success=False)
                    return StageResult.paused()

                if result.timed_out:
                    return StageResult.timeout(result.timeout_seconds or timeout)

                # Process completed - analyze output
                full_output = result.output

                # Check for common error conditions
                if "quota" in full_output.lower() or "rate limit" in full_output.lower():
                    if ui:
                        ui.add_activity("Rate limited", "🚦")
                    error_ctx = analyze_error(
                        output=full_output,
                        exit_code=result.exit_code,
                        error_message="Gemini rate limited",
                        backend=self.name,
                    )
                    return StageResult.error(
                        message="Rate limited by Gemini API",
                        output=full_output,
                        error_context=error_ctx,
                    )

                # Extract result text from streaming JSON output
                result_text = self._extract_result_text(full_output)

                if result.exit_code == 0:
                    if ui:
                        ui.add_activity("Gemini completed", "✅")
                        ui.finish(success=True)
                    return StageResult.create_success(
                        message=result_text[:200] if result_text else "Stage completed",
                        output=full_output,
                    )

                # Analyze the error
                error_ctx = analyze_error(
                    output=full_output,
                    exit_code=result.exit_code,
                    error_message=f"Gemini failed (exit {result.exit_code})",
                    backend=self.name,
                )

                if ui:
                    ui.add_activity(f"Gemini failed (exit {result.exit_code})", "❌")
                    ui.finish(success=False)

                return StageResult.error(
                    message=error_ctx.message,
                    output=full_output,
                    error_context=error_ctx,
                )

        except Exception as e:
            error_ctx = analyze_error(
                output=str(e),
                error_message=f"Gemini invocation error: {e}",
                backend=self.name,
            )
            if ui:
                ui.finish(success=False)
            return StageResult.error(
                message=error_ctx.message,
                output=str(e),
                error_context=error_ctx,
            )

    def _process_stream_line(self, line: str, ui: StageUI | None) -> None:
        """
        Process a single line of streaming output.

        Gemini's streaming JSON format differs from Claude's. This method
        handles both JSON and plain text output formats.
        """
        if not line.strip():
            return

        try:
            data = json.loads(line.strip())
            msg_type = data.get("type", "")

            if msg_type == "content":
                # Content chunk
                if ui:
                    ui.set_status("generating", "response")

            elif msg_type == "tool_use":
                # Gemini tool use (if supported)
                tool_name = data.get("name", "tool")
                if ui:
                    ui.add_activity(f"Tool: {tool_name}", "🔧")
                    ui.set_status("executing", tool_name)

            elif msg_type == "error":
                error_msg = data.get("message", "Unknown error")
                if ui:
                    ui.add_activity(f"Error: {error_msg[:60]}", "❌")

            elif msg_type == "status":
                status = data.get("status", "")
                if ui and status:
                    ui.set_status("running", status)

        except json.JSONDecodeError:
            # Plain text output - Gemini may output raw text
            if ui and line.strip():
                # Show significant lines as activity
                stripped = line.strip()
                if len(stripped) > 10 and not stripped.startswith("#"):
                    ui.set_status("generating", "response")

    def _extract_result_text(self, output: str) -> str:
        """
        Extract the result text from Gemini output.

        Handles both streaming JSON and plain text formats.

        Args:
            output: Full output from Gemini

        Returns:
            Extracted result text
        """
        result_parts: list[str] = []

        for line in output.splitlines():
            if not line.strip():
                continue

            try:
                data = json.loads(line.strip())

                # Look for result message
                if data.get("type") == "result":
                    return data.get("text", data.get("content", ""))

                # Accumulate content chunks
                if data.get("type") == "content":
                    text = data.get("text", data.get("content", ""))
                    if text:
                        result_parts.append(text)

            except json.JSONDecodeError:
                # Plain text line - accumulate it
                result_parts.append(line)

        return "\n".join(result_parts)

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """
        Simple text generation with Gemini.

        Args:
            prompt: The prompt to send
            timeout: Maximum time in seconds

        Returns:
            Generated text, or empty string on failure
        """
        try:
            with self._temp_file(prompt, suffix=".txt") as prompt_file:
                # Use config command or default
                command = self._config.command if self._config else self.DEFAULT_COMMAND

                # Simple text output mode
                shell_cmd = f"cat '{prompt_file}' | {command} --output-format text"
                result = subprocess.run(
                    shell_cmd,
                    shell=True,
                    cwd=get_project_root(),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()

        except (subprocess.TimeoutExpired, Exception) as e:
            logger.debug("gemini_generate_text_error", error=str(e))

        return ""
