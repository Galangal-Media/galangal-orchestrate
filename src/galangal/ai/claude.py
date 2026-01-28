"""
Claude CLI backend implementation.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from galangal.ai.base import AIBackend, PauseCheck
from galangal.ai.errors import analyze_error
from galangal.ai.subprocess import SubprocessRunner
from galangal.config.loader import get_project_root
from galangal.logging import get_logger
from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI

logger = get_logger(__name__)


class ClaudeBackend(AIBackend):
    """Claude CLI backend."""

    # Default command and args when no config provided
    DEFAULT_COMMAND = "claude"
    DEFAULT_ARGS = [
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "{max_turns}",
        "--permission-mode",
        "bypassPermissions",
    ]

    @property
    def name(self) -> str:
        return "claude"

    def _build_command(self, prompt_file: str, max_turns: int) -> str:
        """
        Build the shell command to invoke Claude.

        Uses config.command and config.args if available, otherwise falls back
        to hard-coded defaults for backwards compatibility.

        Args:
            prompt_file: Path to temp file containing the prompt
            max_turns: Maximum conversation turns

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
        max_turns: int = 200,
        ui: StageUI | None = None,
        pause_check: PauseCheck | None = None,
        stage: str | None = None,
        log_file: str | None = None,
    ) -> StageResult:
        """Invoke Claude Code with a prompt."""
        # State for output processing
        pending_tools: list[tuple[str, str]] = []

        def on_output(line: str) -> None:
            """Process each output line."""
            if ui:
                ui.add_raw_line(line)
            self._process_stream_line(line, ui, pending_tools)
            # Stream to hub for remote monitoring
            try:
                from galangal.hub.hooks import notify_output
                notify_output(line, "raw")
            except Exception:
                pass  # Hub streaming is non-critical

        def on_idle(elapsed: float) -> None:
            """Update status when idle."""
            if ui:
                if pending_tools:
                    tool_name = pending_tools[-1][1]
                    ui.set_status("waiting", f"{tool_name}...")
                else:
                    ui.set_status("waiting", "API response")

        try:
            with self._temp_file(prompt, suffix=".txt") as prompt_file:
                shell_cmd = self._build_command(prompt_file, max_turns)

                if ui:
                    ui.set_status("starting", "initializing Claude")

                runner = SubprocessRunner(
                    command=shell_cmd,
                    timeout=timeout,
                    pause_check=pause_check,
                    ui=ui,
                    on_output=on_output,
                    on_idle=on_idle,
                    idle_interval=3.0,
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

                if "max turns" in full_output.lower() or "reached max" in full_output.lower():
                    if ui:
                        ui.add_activity("Max turns reached", "❌")
                    return StageResult.max_turns(full_output)

                # Extract result from JSON stream
                result_text = ""
                for line in full_output.splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line.strip())
                        if data.get("type") == "result":
                            result_text = data.get("result", "")
                            if ui:
                                ui.set_turns(data.get("num_turns", 0))
                            break
                    except json.JSONDecodeError as e:
                        logger.debug("json_decode_error", error=str(e), line=line[:100])
                    except (KeyError, TypeError):
                        pass

                if result.exit_code == 0:
                    return StageResult.create_success(
                        message=result_text or "Stage completed",
                        output=full_output,
                    )

                # Analyze the error for better diagnostics
                error_ctx = analyze_error(
                    output=full_output,
                    exit_code=result.exit_code,
                    error_message=f"Claude failed (exit {result.exit_code})",
                    backend=self.name,
                )
                return StageResult.error(
                    message=error_ctx.message,
                    output=full_output,
                    error_context=error_ctx,
                )

        except Exception as e:
            # Analyze exception-based errors too
            error_ctx = analyze_error(
                output=str(e),
                error_message=f"Claude invocation error: {e}",
                backend=self.name,
            )
            return StageResult.error(
                message=error_ctx.message,
                output=str(e),
                error_context=error_ctx,
            )

    def _process_stream_line(
        self,
        line: str,
        ui: StageUI | None,
        pending_tools: list[tuple[str, str]],
    ) -> None:
        """Process a single line of streaming output."""
        if not line.strip():
            return

        try:
            data = json.loads(line.strip())
            msg_type = data.get("type", "")

            if msg_type == "assistant" and "tool_use" in str(data):
                self._handle_assistant_message(data, ui, pending_tools)
            elif msg_type == "user":
                self._handle_user_message(data, ui, pending_tools)
            elif msg_type == "system":
                self._handle_system_message(data, ui)

        except json.JSONDecodeError as e:
            logger.debug("json_decode_error", error=str(e), line=line[:100])
        except (KeyError, TypeError):
            pass

    def _handle_assistant_message(
        self,
        data: dict[str, Any],
        ui: StageUI | None,
        pending_tools: list[tuple[str, str]],
    ) -> None:
        """Handle assistant message with tool use."""
        content = data.get("message", {}).get("content", [])

        for item in content:
            if item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                tool_id = item.get("id", "")
                if tool_id:
                    pending_tools.append((tool_id, tool_name))

                if ui:
                    if tool_name in ["Write", "Edit"]:
                        tool_input = item.get("input", {})
                        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
                        if file_path:
                            short_path = file_path.split("/")[-1] if "/" in file_path else file_path
                            ui.add_activity(f"{tool_name}: {short_path}", "✏️", verbose_only=True)
                            ui.set_status("writing", short_path)

                    elif tool_name == "Read":
                        tool_input = item.get("input", {})
                        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
                        if file_path:
                            short_path = file_path.split("/")[-1] if "/" in file_path else file_path
                            ui.add_activity(f"Read: {short_path}", "📖", verbose_only=True)
                            ui.set_status("reading", short_path)

                    elif tool_name == "Bash":
                        cmd_preview = item.get("input", {}).get("command", "")[:140]
                        ui.add_activity(f"Bash: {cmd_preview}", "🔧", verbose_only=True)
                        ui.set_status("running", "bash")

                    elif tool_name in ["Grep", "Glob"]:
                        pattern = item.get("input", {}).get("pattern", "")[:80]
                        ui.add_activity(f"{tool_name}: {pattern}", "🔍", verbose_only=True)
                        ui.set_status("searching", pattern[:40])

                    elif tool_name == "Task":
                        desc = item.get("input", {}).get("description", "agent")
                        ui.add_activity(f"Task: {desc}", "🤖", verbose_only=True)
                        ui.set_status("agent", desc[:25])

                    elif tool_name not in ["TodoWrite"]:
                        ui.add_activity(f"{tool_name}", "⚡", verbose_only=True)
                        ui.set_status("executing", tool_name)

            elif item.get("type") == "text":
                # Show Claude's text responses (always visible, not verbose-only)
                text = item.get("text", "").strip()
                if text and ui:
                    # Wrap long lines to avoid horizontal scrolling
                    import textwrap
                    wrapped_lines = []
                    for line in text.split("\n"):
                        if len(line) > 100:
                            # Wrap long lines, preserving any leading whitespace
                            wrapped = textwrap.fill(
                                line,
                                width=100,
                                break_long_words=False,
                                break_on_hyphens=False,
                            )
                            wrapped_lines.append(wrapped)
                        else:
                            wrapped_lines.append(line)
                    wrapped_text = "\n".join(wrapped_lines)
                    ui.add_activity(wrapped_text, "💬", verbose_only=False)

            elif item.get("type") == "thinking":
                if ui:
                    ui.set_status("thinking")

    def _handle_user_message(
        self,
        data: dict[str, Any],
        ui: StageUI | None,
        pending_tools: list[tuple[str, str]],
    ) -> None:
        """Handle user message with tool results."""
        content = data.get("message", {}).get("content", [])

        for item in content:
            if item.get("type") == "tool_result":
                tool_id = item.get("tool_use_id", "")
                is_error = item.get("is_error", False)
                pending_tools[:] = [(tid, tname) for tid, tname in pending_tools if tid != tool_id]
                if is_error and ui:
                    ui.set_status("error", "tool failed")

    def _handle_system_message(self, data: dict[str, Any], ui: StageUI | None) -> None:
        """Handle system messages."""
        message = data.get("message", "")
        subtype = data.get("subtype", "")

        if "rate" in message.lower():
            if ui:
                ui.add_activity("Rate limited - waiting", "🚦")
                ui.set_status("rate_limited", "waiting...")
        elif subtype and ui:
            ui.set_status(subtype)

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """Simple text generation."""
        try:
            with self._temp_file(prompt, suffix=".txt") as prompt_file:
                # Use config command or default
                command = self._config.command if self._config else self.DEFAULT_COMMAND

                # Pipe file content to claude via stdin (simple text output mode)
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
        except (subprocess.TimeoutExpired, Exception):
            pass
        return ""
