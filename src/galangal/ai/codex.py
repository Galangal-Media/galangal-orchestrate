"""
Codex CLI backend implementation for read-only code review.

Uses OpenAI's Codex in non-interactive mode with structured JSON output.
See: https://developers.openai.com/codex/noninteractive
"""

from __future__ import annotations

import json
import os
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
    Codex CLI backend for read-only code review.

    Key characteristics:
    - Runs in read-only sandbox by default (cannot write files)
    - Uses --output-schema for structured JSON output
    - Artifacts must be written by post-processing the output
    """

    # Default command and args when no config provided
    DEFAULT_COMMAND = "codex"
    DEFAULT_ARGS = [
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

    def _build_command(
        self,
        prompt_file: str,
        schema_file: str,
        output_file: str,
    ) -> str:
        """
        Build the shell command to invoke Codex.

        Uses config.command and config.args if available, otherwise falls back
        to hard-coded defaults for backwards compatibility.

        Args:
            prompt_file: Path to temp file containing the prompt
            schema_file: Path to JSON schema file
            output_file: Path for structured output

        Returns:
            Shell command string ready for subprocess
        """
        if self._config:
            command = self._config.command
            args = self._substitute_placeholders(
                self._config.args,
                schema_file=schema_file,
                output_file=output_file,
            )
        else:
            # Backwards compatibility: use defaults
            command = self.DEFAULT_COMMAND
            args = self._substitute_placeholders(
                self.DEFAULT_ARGS,
                schema_file=schema_file,
                output_file=output_file,
            )

        args_str = " ".join(f"'{a}'" if " " in a else a for a in args)
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
        """
        Invoke Codex in non-interactive read-only mode.

        Uses --output-schema to enforce structured JSON output with:
        - Stage-specific notes field (qa_report, security_checklist, review_notes)
        - decision: Stage-appropriate values (PASS/FAIL, APPROVED/REJECTED, etc.)
        - issues: Array of specific problems found

        Args:
            prompt: The full prompt to send
            timeout: Maximum time in seconds
            max_turns: Maximum conversation turns (unused for Codex)
            ui: Optional TUI for progress display
            pause_check: Optional callback for pause detection
            stage: Stage name for schema customization (e.g., "QA", "SECURITY")
            log_file: Optional path to log file for streaming raw output

        Returns:
            StageResult with structured JSON in the output field
        """
        # Track timing for activity updates
        start_time = time.time()
        last_activity_time = start_time

        def on_output(line: str) -> None:
            """Process each output line."""
            nonlocal last_activity_time
            line = line.strip()
            # Show meaningful output lines, skip raw JSON
            if line and not line.startswith("{"):
                if ui:
                    ui.add_activity(f"codex: {line[:80]}", "💬")
                last_activity_time = time.time()

        def on_idle(elapsed: float) -> None:
            """Update status periodically."""
            nonlocal last_activity_time
            if not ui:
                return

            # Update status with elapsed time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            ui.set_status("running", f"Codex reviewing code ({time_str})")

            # Add activity update if no output for 30 seconds
            current_time = time.time()
            if current_time - last_activity_time >= 30.0:
                if minutes > 0:
                    ui.add_activity(f"Still reviewing... ({minutes}m elapsed)", "⏳")
                else:
                    ui.add_activity("Still reviewing...", "⏳")
                last_activity_time = current_time

        try:
            # Create temp files for prompt, schema, and output
            output_schema = _build_output_schema(stage)
            schema_content = json.dumps(output_schema)
            with (
                self._temp_file(prompt, suffix=".txt") as prompt_file,
                self._temp_file(schema_content, suffix=".json") as schema_file,
                self._temp_file(suffix=".json") as output_file,
            ):
                if ui:
                    ui.set_status("starting", "initializing Codex")

                shell_cmd = self._build_command(prompt_file, schema_file, output_file)

                if ui:
                    ui.set_status("running", "Codex reviewing code")
                    ui.add_activity("Codex code review started", "🔍")

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

                # Process completed
                if result.exit_code != 0:
                    if ui:
                        ui.add_activity(f"Codex failed (exit {result.exit_code})", "❌")
                        ui.finish(success=False)
                    return StageResult.error(
                        message=f"Codex failed (exit {result.exit_code})",
                        output=result.output,
                    )

                # Read the structured output
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

                # Validate JSON structure
                try:
                    output_data = json.loads(output_content)
                    decision = output_data.get("decision", "")

                    if ui:
                        issues_count = len(output_data.get("issues", []))
                        elapsed = time.time() - start_time
                        minutes = int(elapsed // 60)
                        seconds = int(elapsed % 60)
                        time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

                        if decision == "APPROVE":
                            ui.add_activity(
                                f"Review complete: APPROVED ({issues_count} suggestions) in {time_str}",
                                "✅",
                            )
                        else:
                            ui.add_activity(
                                f"Review complete: {issues_count} issues found in {time_str}",
                                "⚠️",
                            )
                        ui.finish(success=True)

                    return StageResult.create_success(
                        message=f"Codex review complete: {decision}",
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
