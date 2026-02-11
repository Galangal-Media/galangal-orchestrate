"""
Codex CLI backend implementation.

Supports two modes:
- Editable mode (default): Codex can modify files directly, similar to Claude.
- Read-only mode (opt-in): Codex returns structured JSON for post-processing.

Read-only mode is primarily useful for independent review stages where
artifact writing is handled outside the backend.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from typing import TYPE_CHECKING, Any

from galangal.ai.base import AIBackend, PauseCheck
from galangal.ai.subprocess import SubprocessRunner
from galangal.config.loader import get_project_root
from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI


def _build_output_schema(stage: str | None) -> dict[str, Any]:
    """
    Build stage-specific JSON output schema.

    Derives artifact field names and decision values from STAGE_METADATA.
    Falls back to generic review schema if stage not found.

    Args:
        stage: Stage name (e.g., "QA", "SECURITY", "REVIEW")

    Returns:
        JSON schema dict for structured output
    """
    from galangal.core.state import Stage, get_decision_values

    # Defaults for unknown or unspecified stages
    notes_field = "review_notes"
    notes_description = "Full review findings in markdown format"
    decision_values = ["APPROVE", "REQUEST_CHANGES"]

    if stage:
        try:
            stage_enum = Stage.from_str(stage)
            metadata = stage_enum.metadata

            # Derive notes field from produces_artifacts
            if metadata.produces_artifacts:
                artifact_name = metadata.produces_artifacts[0]
                # Convert "QA_REPORT.md" -> "qa_report"
                notes_field = artifact_name.lower().replace(".md", "")
                notes_description = f"{metadata.display_name} findings in markdown format"

            # Get decision values from metadata
            values = get_decision_values(stage_enum)
            if values:
                decision_values = values

        except (ValueError, AttributeError):
            # Stage not found or invalid, use defaults
            pass

    return {
        "type": "object",
        "properties": {
            notes_field: {
                "type": "string",
                "description": notes_description,
            },
            "decision": {
                "type": "string",
                "enum": decision_values,
                "description": "Stage decision",
            },
            "issues": {
                "type": "array",
                "description": "List of specific issues found",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "major", "minor", "suggestion"],
                        },
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "description": {"type": "string"},
                    },
                    "required": ["severity", "file", "line", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [notes_field, "decision", "issues"],
        "additionalProperties": False,
    }


class CodexBackend(AIBackend):
    """
    Codex CLI backend.

    Default behavior is editable execution, so Codex can modify files and
    produce stage artifacts directly. If configured with ``read_only: true``,
    this backend switches to structured JSON output for post-processing.
    """

    # Default command and args when no config provided
    DEFAULT_COMMAND = "codex"
    DEFAULT_ARGS = [
        "exec",
        "--full-auto",
    ]
    DEFAULT_READ_ONLY_ARGS = [
        "exec",
        "--full-auto",
        "--output-schema",
        "{schema_file}",
        "-o",
        "{output_file}",
    ]

    @property
    def name(self) -> str:
        return "codex"

    def _build_command(self, prompt_file: str, args: list[str]) -> str:
        """Build the shell command to invoke Codex."""
        command = self._config.command if self._config else self.DEFAULT_COMMAND
        args_str = " ".join(shlex.quote(a) for a in args)
        return f"cat {shlex.quote(prompt_file)} | {shlex.quote(command)} {args_str}"

    def _read_only_args(self, schema_file: str, output_file: str, max_turns: int) -> list[str]:
        """Get read-only args with required placeholders applied."""
        if self._config and self._config.args:
            args = list(self._config.args)
        else:
            args = list(self.DEFAULT_READ_ONLY_ARGS)

        if not any("{schema_file}" in arg for arg in args):
            args.extend(["--output-schema", "{schema_file}"])
        if not any("{output_file}" in arg for arg in args):
            args.extend(["-o", "{output_file}"])

        return self._substitute_placeholders(
            args,
            schema_file=schema_file,
            output_file=output_file,
            max_turns=max_turns,
        )

    def _editable_args(self, max_turns: int) -> list[str]:
        """Get editable args for normal stage execution."""
        if self._config and self._config.args:
            args = list(self._config.args)
        else:
            args = list(self.DEFAULT_ARGS)

        return self._substitute_placeholders(args, max_turns=max_turns)

    def _run_subprocess(
        self,
        shell_cmd: str,
        timeout: int,
        pause_check: PauseCheck | None,
        ui: StageUI | None,
        on_output,
        on_idle,
        log_file: str | None,
    ):
        """Run the codex command via shared subprocess runner."""
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
        return runner.run()

    def _invoke_read_only(
        self,
        prompt: str,
        timeout: int,
        max_turns: int,
        ui: StageUI | None,
        pause_check: PauseCheck | None,
        stage: str | None,
        log_file: str | None,
    ) -> StageResult:
        """Invoke Codex in read-only structured-output mode."""
        start_time = time.time()
        last_activity_time = start_time

        def on_output(line: str) -> None:
            nonlocal last_activity_time
            if ui:
                ui.add_raw_line(line)
            line = line.strip()
            if line and not line.startswith("{"):
                if ui:
                    ui.add_activity(f"codex: {line[:80]}", "💬")
                last_activity_time = time.time()

        def on_idle(elapsed: float) -> None:
            nonlocal last_activity_time
            if not ui:
                return

            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            ui.set_status("running", f"Codex running (read-only, {time_str})")

            current_time = time.time()
            if current_time - last_activity_time >= 30.0:
                if minutes > 0:
                    ui.add_activity(f"Still running... ({minutes}m elapsed)", "⏳")
                else:
                    ui.add_activity("Still running...", "⏳")
                last_activity_time = current_time

        try:
            output_schema = _build_output_schema(stage)
            schema_content = json.dumps(output_schema)
            with (
                self._temp_file(prompt, suffix=".txt") as prompt_file,
                self._temp_file(schema_content, suffix=".json") as schema_file,
                self._temp_file(suffix=".json") as output_file,
            ):
                if ui:
                    ui.set_status("starting", "initializing Codex")
                    ui.add_activity("Codex read-only run started", "🔍")

                args = self._read_only_args(schema_file, output_file, max_turns)
                shell_cmd = self._build_command(prompt_file, args)

                result = self._run_subprocess(
                    shell_cmd=shell_cmd,
                    timeout=timeout,
                    pause_check=pause_check,
                    ui=ui,
                    on_output=on_output,
                    on_idle=on_idle,
                    log_file=log_file,
                )

                if result.paused:
                    if ui:
                        ui.finish(success=False)
                    return StageResult.paused()

                if result.timed_out:
                    return StageResult.timeout(result.timeout_seconds or timeout)

                if result.exit_code != 0:
                    if ui:
                        ui.add_activity(f"Codex failed (exit {result.exit_code})", "❌")
                        ui.finish(success=False)
                    return StageResult.error(
                        message=f"Codex failed (exit {result.exit_code})",
                        output=result.output,
                    )

                if not os.path.exists(output_file):
                    if ui:
                        ui.add_activity("No output file generated", "❌")
                        ui.finish(success=False)
                    debug_output = f"Expected output at: {output_file}\nOutput:\n{result.output}"
                    return StageResult.error(
                        message="Codex did not produce output file. Check if --output-schema is supported.",
                        output=debug_output,
                    )

                with open(output_file, encoding="utf-8") as f:
                    output_content = f.read()

                try:
                    output_data = json.loads(output_content)
                    decision = output_data.get("decision", "")

                    if ui:
                        issues_count = len(output_data.get("issues", []))
                        elapsed = time.time() - start_time
                        minutes = int(elapsed // 60)
                        seconds = int(elapsed % 60)
                        time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

                        if decision in {"APPROVE", "APPROVED", "PASS"}:
                            ui.add_activity(
                                f"Codex complete: {decision} ({issues_count} issues) in {time_str}",
                                "✅",
                            )
                        else:
                            ui.add_activity(
                                f"Codex complete: {decision or 'done'} ({issues_count} issues) in {time_str}",
                                "⚠️",
                            )
                        ui.finish(success=True)

                    return StageResult.create_success(
                        message=f"Codex structured run complete: {decision or 'DONE'}",
                        output=output_content,
                    )

                except json.JSONDecodeError as e:
                    if ui:
                        ui.add_activity("Invalid JSON output", "❌")
                        ui.finish(success=False)
                    return StageResult.error(
                        message=f"Codex output is not valid JSON: {e}",
                        output=output_content,
                    )

        except Exception as e:
            if ui:
                ui.finish(success=False)
            return StageResult.error(f"Codex invocation error: {e}")

    def _invoke_editable(
        self,
        prompt: str,
        timeout: int,
        max_turns: int,
        ui: StageUI | None,
        pause_check: PauseCheck | None,
        log_file: str | None,
    ) -> StageResult:
        """Invoke Codex in editable mode (default)."""
        start_time = time.time()

        def on_output(line: str) -> None:
            if ui:
                ui.add_raw_line(line)
            stripped = line.strip()
            if ui and stripped and not stripped.startswith("{"):
                ui.add_activity(f"codex: {stripped[:100]}", "💬", verbose_only=True)

        def on_idle(elapsed: float) -> None:
            if not ui:
                return
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            ui.set_status("running", f"Codex executing ({time_str})")

        try:
            with self._temp_file(prompt, suffix=".txt") as prompt_file:
                if ui:
                    ui.set_status("starting", "initializing Codex")
                    ui.add_activity("Codex stage execution started", "🤖")

                args = self._editable_args(max_turns)
                shell_cmd = self._build_command(prompt_file, args)

                result = self._run_subprocess(
                    shell_cmd=shell_cmd,
                    timeout=timeout,
                    pause_check=pause_check,
                    ui=ui,
                    on_output=on_output,
                    on_idle=on_idle,
                    log_file=log_file,
                )

                if result.paused:
                    if ui:
                        ui.finish(success=False)
                    return StageResult.paused()

                if result.timed_out:
                    return StageResult.timeout(result.timeout_seconds or timeout)

                output = result.output

                if "max turns" in output.lower() or "reached max" in output.lower():
                    if ui:
                        ui.add_activity("Max turns reached", "❌")
                        ui.finish(success=False)
                    return StageResult.max_turns(output)

                if result.exit_code == 0:
                    if ui:
                        elapsed = int(time.time() - start_time)
                        ui.add_activity(f"Codex completed in {elapsed}s", "✅")
                        ui.finish(success=True)
                    return StageResult.create_success(
                        message="Stage completed",
                        output=output,
                    )

                if ui:
                    ui.add_activity(f"Codex failed (exit {result.exit_code})", "❌")
                    ui.finish(success=False)
                return StageResult.error(
                    message=f"Codex failed (exit {result.exit_code})",
                    output=output,
                )

        except Exception as e:
            if ui:
                ui.finish(success=False)
            return StageResult.error(f"Codex invocation error: {e}")

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
        Invoke Codex for a stage execution.

        - If ``read_only`` is enabled in backend config, uses structured JSON mode.
        - Otherwise uses editable mode (default), allowing Codex to modify files.
        """
        if self.read_only:
            return self._invoke_read_only(
                prompt=prompt,
                timeout=timeout,
                max_turns=max_turns,
                ui=ui,
                pause_check=pause_check,
                stage=stage,
                log_file=log_file,
            )

        return self._invoke_editable(
            prompt=prompt,
            timeout=timeout,
            max_turns=max_turns,
            ui=ui,
            pause_check=pause_check,
            log_file=log_file,
        )

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """
        Simple text generation using Codex.

        Note: For simple text generation, we use codex exec without
        structured output schema.
        """
        try:
            with (
                self._temp_file(prompt, suffix=".txt") as prompt_file,
                self._temp_file(suffix=".txt") as output_file,
            ):
                # Use config command or default
                command = self._config.command if self._config else self.DEFAULT_COMMAND
                shell_cmd = f"cat '{prompt_file}' | {command} exec -o '{output_file}'"

                result = subprocess.run(
                    shell_cmd,
                    shell=True,
                    cwd=get_project_root(),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                if result.returncode == 0 and os.path.exists(output_file):
                    with open(output_file, encoding="utf-8") as f:
                        return f.read().strip()

        except (subprocess.TimeoutExpired, Exception):
            pass

        return ""
