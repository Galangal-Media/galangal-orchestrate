"""
Claude CLI backend implementation.
"""

from __future__ import annotations

import json
import random
import shlex
import time
from typing import TYPE_CHECKING, Any

from galangal.ai.base import AIBackend, PauseCheck
from galangal.ai.errors import ErrorCategory, analyze_error
from galangal.ai.subprocess import SubprocessRunner
from galangal.config.loader import get_config, get_project_root
from galangal.logging import get_logger
from galangal.results import StageResult, StageResultType

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

    def _build_command(
        self,
        prompt_file: str,
        max_turns: int,
        resume_session: str | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> str:
        """Build the shell command to invoke Claude.

        ``disallowed_tools`` denies specific tools for this stage (e.g. Edit on a
        planning stage); ``resume_session`` continues a prior session after a
        max-turns ceiling instead of starting fresh.
        """
        command, args = self._resolve_command_and_args(max_turns)
        args = self._with_model(args)
        if disallowed_tools:
            args = [*args, "--disallowedTools", ",".join(disallowed_tools)]
        if resume_session:
            args = [*args, "--resume", resume_session]
        args_str = " ".join(args)
        return f"cat '{prompt_file}' | {command} {args_str}"

    def _with_model(self, args: list[str]) -> list[str]:
        """Append --model when a model is configured (and not already present).

        If no model is configured, the Claude CLI's own default model is used.
        """
        model = self._config.model if self._config else None
        if model and "--model" not in args:
            return [*args, "--model", model]
        return args

    # Continuation prompt fed to a resumed session that hit the turn ceiling.
    _RESUME_PROMPT = (
        "You ran out of turns before finishing. Continue exactly where you left "
        "off and complete the remaining work for this stage. Do not restart from "
        "scratch or re-do work already done; finish and write all required "
        "artifacts."
    )

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
        """Invoke Claude Code with a prompt.

        On a max-turns ceiling, optionally resume the same session up to
        ``stages.max_turns_resume_limit`` times to finish the work instead of
        discarding it (the legacy behavior, when the limit is 0).
        """
        config = get_config()
        no_progress = config.stages.no_progress_timeout
        resume_limit = config.stages.max_turns_resume_limit
        transient_limit = config.stages.transient_retry_limit
        disallowed = (
            config.stages.stage_disallowed_tools.get(stage, []) if stage else []
        )

        captured_session: dict[str, str | None] = {"id": None}
        rate_state: dict[str, bool] = {"limited": False}
        totals: dict[str, Any] = {}
        extensions = 0
        transient_retries = 0
        resume_session: str | None = None
        current_prompt = prompt

        while True:
            result = self._invoke_once(
                prompt=current_prompt,
                timeout=timeout,
                max_turns=max_turns,
                ui=ui,
                pause_check=pause_check,
                log_file=log_file,
                no_progress=no_progress,
                disallowed_tools=disallowed,
                resume_session=resume_session,
                captured_session=captured_session,
                rate_state=rate_state,
                totals=totals,
            )

            # Resume on a max-turns ceiling if we have budget and a session id.
            hit_ceiling = result.type == StageResultType.MAX_TURNS
            if (
                hit_ceiling
                and extensions < resume_limit
                and captured_session["id"]
            ):
                extensions += 1
                resume_session = captured_session["id"]
                current_prompt = self._RESUME_PROMPT
                if ui:
                    ui.add_activity(
                        f"Max turns reached - resuming session "
                        f"({extensions}/{resume_limit})",
                        "🔄",
                    )
                continue

            # Retry transient errors (rate limit / network blip) with jittered
            # backoff, from scratch, instead of failing the whole stage.
            if (
                not result.success
                and result.error_context is not None
                and result.error_context.category
                in (ErrorCategory.RATE_LIMIT, ErrorCategory.NETWORK)
                and transient_retries < transient_limit
            ):
                delay = self._backoff_delay(transient_retries)
                transient_retries += 1
                if ui:
                    ui.add_activity(
                        f"Transient error ({result.error_context.category.name}) - "
                        f"retrying in {delay:.0f}s ({transient_retries}/{transient_limit})",
                        "🔁",
                    )
                time.sleep(delay)
                resume_session = None
                current_prompt = prompt
                continue

            return result

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 5.0, cap: float = 60.0) -> float:
        """Exponential backoff with full jitter, capped."""
        ceiling = min(cap, base * (2**attempt))
        return random.uniform(base, ceiling) if ceiling > base else base

    def _invoke_once(
        self,
        prompt: str,
        timeout: int,
        max_turns: int,
        ui: StageUI | None,
        pause_check: PauseCheck | None,
        log_file: str | None,
        no_progress: int,
        disallowed_tools: list[str],
        resume_session: str | None,
        captured_session: dict[str, str | None],
        rate_state: dict[str, bool],
        totals: dict[str, Any],
    ) -> StageResult:
        """Run Claude once; cost/token metrics accumulate into ``totals``."""
        pending_tools: list[tuple[str, str]] = []

        def on_output(line: str) -> None:
            """Process each output line."""
            if ui:
                ui.add_raw_line(line)
            self._capture_session_id(line, captured_session)
            self._update_rate_state(line, rate_state)
            self._process_stream_line(line, ui, pending_tools)
            self._notify_hub_output(line)

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
                shell_cmd = self._build_command(
                    prompt_file,
                    max_turns,
                    resume_session=resume_session,
                    disallowed_tools=disallowed_tools,
                )

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
                    no_progress_timeout=no_progress,
                    watchdog_suppressed=lambda: rate_state["limited"],
                )

                result = runner.run()

                early_return = self._handle_subprocess_result(result, ui, timeout)
                if early_return is not None:
                    return early_return

                # Process completed - analyze output
                full_output = result.output

                # Extract the structured result event from the JSON stream.
                result_text = ""
                result_subtype = ""
                metrics: dict[str, Any] | None = None
                for line in full_output.splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line.strip())
                        if data.get("type") == "result":
                            result_text = data.get("result", "")
                            result_subtype = data.get("subtype", "")
                            metrics = self._extract_metrics(data)
                            if ui:
                                ui.set_turns(data.get("num_turns", 0))
                            break
                    except json.JSONDecodeError as e:
                        logger.debug("json_decode_error", error=str(e), line=line[:100])
                    except (KeyError, TypeError):
                        pass

                metrics = self._merge_metrics(totals, metrics)
                if metrics and ui:
                    ui.add_activity(self._format_metrics(metrics), "💰")

                # Detect max-turns from the structured result subtype rather than
                # scanning prose (Claude's own output can contain "max turns").
                if result_subtype == "error_max_turns":
                    if ui:
                        ui.add_activity("Max turns reached", "❌")
                    res = StageResult.max_turns(full_output)
                    res.metrics = metrics
                    return res

                if result.exit_code == 0:
                    return StageResult.create_success(
                        message=result_text or "Stage completed",
                        output=full_output,
                        metrics=metrics,
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
                    metrics=metrics,
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

    @staticmethod
    def _capture_session_id(line: str, holder: dict[str, str | None]) -> None:
        """Capture the CLI session id from any stream line that carries one.

        Needed to resume the session if it hits the turn ceiling. The init system
        event and the final result event both include ``session_id``.
        """
        if holder["id"] or '"session_id"' not in line:
            return
        try:
            data = json.loads(line.strip())
        except (json.JSONDecodeError, ValueError):
            return
        sid = data.get("session_id") if isinstance(data, dict) else None
        if isinstance(sid, str) and sid:
            holder["id"] = sid

    @staticmethod
    def _update_rate_state(line: str, rate_state: dict[str, bool]) -> None:
        """Track whether the CLI is currently in a rate-limit wait.

        Set while a system message mentions rate limiting (so the no-progress
        watchdog holds off during the idle wait), and cleared as soon as real
        assistant/user activity resumes.
        """
        try:
            data = json.loads(line.strip())
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        msg_type = data.get("type", "")
        if msg_type == "system":
            message = str(data.get("message", "")).lower()
            if "rate" in message:
                rate_state["limited"] = True
        elif msg_type in ("assistant", "user"):
            rate_state["limited"] = False

    @staticmethod
    def _merge_metrics(
        totals: dict[str, Any], metrics: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Accumulate one run's numeric metrics into ``totals`` and return it.

        Across resumed runs the caller sees the summed cost/tokens, so the task
        budget and reporting count the whole stage, not just the last leg.
        """
        if not metrics:
            return totals or None
        for key, val in metrics.items():
            if isinstance(val, (int, float)):
                totals[key] = round(totals.get(key, 0) + val, 6)
        return totals

    @staticmethod
    def _extract_metrics(data: dict[str, Any]) -> dict[str, Any] | None:
        """Pull cost / token usage out of the Claude CLI ``result`` event.

        The CLI emits a final ``{"type": "result", ...}`` line carrying
        ``total_cost_usd``, ``num_turns`` and a nested ``usage`` block. We capture
        these so a stage's cost is recorded rather than discarded. Returns None if
        nothing useful is present (older CLI versions, partial streams).
        """
        usage = data.get("usage") or {}
        metrics: dict[str, Any] = {}

        cost = data.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            metrics["cost_usd"] = round(float(cost), 4)

        turns = data.get("num_turns")
        if isinstance(turns, int):
            metrics["num_turns"] = turns

        if isinstance(usage, dict):
            for src, dest in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
                ("cache_read_input_tokens", "cache_read_tokens"),
                ("cache_creation_input_tokens", "cache_creation_tokens"),
            ):
                val = usage.get(src)
                if isinstance(val, int):
                    metrics[dest] = val

        return metrics or None

    @staticmethod
    def _format_metrics(metrics: dict[str, Any]) -> str:
        """Render a compact one-line metrics summary for the activity feed."""
        parts: list[str] = []
        if "cost_usd" in metrics:
            parts.append(f"${metrics['cost_usd']:.4f}")
        if "num_turns" in metrics:
            parts.append(f"{metrics['num_turns']} turns")
        tok_in = metrics.get("input_tokens")
        tok_out = metrics.get("output_tokens")
        if tok_in is not None or tok_out is not None:
            parts.append(f"{tok_in or 0}→{tok_out or 0} tok")
        cached = metrics.get("cache_read_tokens")
        if cached:
            parts.append(f"{cached} cached")
        return "Usage: " + ", ".join(parts) if parts else "Usage: (none)"

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

            if msg_type == "assistant":
                # Handle every assistant message: text-only turns (narration and
                # final answers) carry no tool_use block but must still display.
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
                model = self._config.model if self._config else None
                model_flag = f" --model {shlex.quote(model)}" if model else ""

                # Pipe file content to claude via stdin (simple text output mode)
                shell_cmd = (
                    f"cat {shlex.quote(prompt_file)} | "
                    f"{shlex.quote(command)} --output-format text{model_flag}"
                )
                returncode, stdout = self._run_shell_capture(
                    shell_cmd, get_project_root(), timeout
                )
                if returncode == 0 and stdout.strip():
                    return stdout.strip()
        except Exception:
            pass
        return ""
