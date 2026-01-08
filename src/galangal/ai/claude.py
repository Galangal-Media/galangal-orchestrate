"""
Claude CLI backend implementation.
"""

import json
import select
import subprocess
import time
from typing import TYPE_CHECKING, Optional

from galangal.ai.base import AIBackend, PauseCheck
from galangal.config.loader import get_project_root
from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI


class ClaudeBackend(AIBackend):
    """Claude CLI backend."""

    @property
    def name(self) -> str:
        return "claude"

    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui: Optional["StageUI"] = None,
        pause_check: PauseCheck | None = None,
    ) -> StageResult:
        """Invoke Claude Code with a prompt."""
        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "acceptEdits",
        ]

        try:
            process = subprocess.Popen(
                cmd,
                cwd=get_project_root(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output_lines: list[str] = []
            last_status_time = time.time()
            start_time = time.time()
            pending_tools: list[tuple[str, str]] = []

            if ui:
                ui.set_status("starting", "initializing Claude")

            while True:
                retcode = process.poll()

                if process.stdout:
                    ready, _, _ = select.select([process.stdout], [], [], 0.5)

                    if ready:
                        line = process.stdout.readline()
                        if line:
                            output_lines.append(line)
                            if ui:
                                ui.add_raw_line(line)
                            self._process_stream_line(line, ui, pending_tools)
                    else:
                        idle_time = time.time() - last_status_time
                        if idle_time > 3 and ui:
                            if pending_tools:
                                tool_name = pending_tools[-1][1]
                                ui.set_status("waiting", f"{tool_name}...")
                            else:
                                ui.set_status("waiting", "API response")
                            last_status_time = time.time()

                if retcode is not None:
                    break

                # Check for pause request via callback
                if pause_check and pause_check():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    if ui:
                        ui.add_activity("Paused by user request", "⏸️")
                        ui.finish(success=False)
                    return StageResult.paused()

                if time.time() - start_time > timeout:
                    process.kill()
                    if ui:
                        ui.add_activity(f"Timeout after {timeout}s", "❌")
                    return StageResult.timeout(timeout)

            remaining_out, _ = process.communicate(timeout=10)
            if remaining_out:
                output_lines.append(remaining_out)

            full_output = "".join(output_lines)

            if "max turns" in full_output.lower() or "reached max" in full_output.lower():
                if ui:
                    ui.add_activity("Max turns reached", "❌")
                return StageResult.max_turns(full_output)

            result_text = ""
            for line in output_lines:
                try:
                    data = json.loads(line.strip())
                    if data.get("type") == "result":
                        result_text = data.get("result", "")
                        if ui:
                            ui.set_turns(data.get("num_turns", 0))
                        break
                except (json.JSONDecodeError, KeyError):
                    pass

            if process.returncode == 0:
                return StageResult.success(
                    message=result_text or "Stage completed",
                    output=full_output,
                )
            return StageResult.error(
                message=f"Claude failed (exit {process.returncode})",
                output=full_output,
            )

        except subprocess.TimeoutExpired:
            process.kill()
            return StageResult.timeout(timeout)
        except Exception as e:
            return StageResult.error(f"Claude invocation error: {e}")

    def _process_stream_line(
        self,
        line: str,
        ui: Optional["StageUI"],
        pending_tools: list[tuple[str, str]],
    ) -> None:
        """Process a single line of streaming output."""
        try:
            data = json.loads(line.strip())
            msg_type = data.get("type", "")

            if msg_type == "assistant" and "tool_use" in str(data):
                self._handle_assistant_message(data, ui, pending_tools)
            elif msg_type == "user":
                self._handle_user_message(data, ui, pending_tools)
            elif msg_type == "system":
                self._handle_system_message(data, ui)

        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    def _handle_assistant_message(
        self,
        data: dict,
        ui: Optional["StageUI"],
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
                            ui.add_activity(f"{tool_name}: {short_path}", "✏️")
                            ui.set_status("writing", short_path)

                    elif tool_name == "Read":
                        tool_input = item.get("input", {})
                        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
                        if file_path:
                            short_path = file_path.split("/")[-1] if "/" in file_path else file_path
                            ui.add_activity(f"Read: {short_path}", "📖")
                            ui.set_status("reading", short_path)

                    elif tool_name == "Bash":
                        cmd_preview = item.get("input", {}).get("command", "")[:140]
                        ui.add_activity(f"Bash: {cmd_preview}", "🔧")
                        ui.set_status("running", "bash")

                    elif tool_name in ["Grep", "Glob"]:
                        pattern = item.get("input", {}).get("pattern", "")[:80]
                        ui.add_activity(f"{tool_name}: {pattern}", "🔍")
                        ui.set_status("searching", pattern[:40])

                    elif tool_name == "Task":
                        desc = item.get("input", {}).get("description", "agent")
                        ui.add_activity(f"Task: {desc}", "🤖")
                        ui.set_status("agent", desc[:25])

                    elif tool_name not in ["TodoWrite"]:
                        ui.add_activity(f"{tool_name}", "⚡")
                        ui.set_status("executing", tool_name)

            elif item.get("type") == "thinking":
                if ui:
                    ui.set_status("thinking")

    def _handle_user_message(
        self,
        data: dict,
        ui: Optional["StageUI"],
        pending_tools: list[tuple[str, str]],
    ) -> None:
        """Handle user message with tool results."""
        content = data.get("message", {}).get("content", [])

        for item in content:
            if item.get("type") == "tool_result":
                tool_id = item.get("tool_use_id", "")
                is_error = item.get("is_error", False)
                pending_tools[:] = [
                    (tid, tname) for tid, tname in pending_tools if tid != tool_id
                ]
                if is_error and ui:
                    ui.set_status("error", "tool failed")

    def _handle_system_message(self, data: dict, ui: Optional["StageUI"]) -> None:
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
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
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
