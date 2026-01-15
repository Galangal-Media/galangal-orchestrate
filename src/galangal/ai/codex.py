"""
Codex CLI backend implementation for read-only code review.

Uses OpenAI's Codex in non-interactive mode with structured JSON output.
See: https://developers.openai.com/codex/noninteractive
"""

import json
import os
import select
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Any, Optional

from galangal.ai.base import AIBackend, PauseCheck
from galangal.config.loader import get_project_root
from galangal.results import StageResult

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI


# JSON Schema for structured review output
# Note: OpenAI API requires:
# - additionalProperties: false at all levels
# - ALL properties must be in the required array
REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "review_notes": {
            "type": "string",
            "description": "Full review findings in markdown format",
        },
        "decision": {
            "type": "string",
            "enum": ["APPROVE", "REQUEST_CHANGES"],
            "description": "Review decision",
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
    "required": ["review_notes", "decision", "issues"],
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
        "--output-schema", "{schema_file}",
        "-o", "{output_file}",
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
        ui: Optional["StageUI"] = None,
        pause_check: PauseCheck | None = None,
    ) -> StageResult:
        """
        Invoke Codex in non-interactive read-only mode.

        Uses --output-schema to enforce structured JSON output with:
        - review_notes: Full review findings (markdown)
        - decision: APPROVE or REQUEST_CHANGES
        - issues: Array of specific problems found

        Returns:
            StageResult with structured JSON in the output field
        """
        prompt_file = None
        schema_file = None
        output_file = None

        try:
            # Create temp files for prompt, schema, and output
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                json.dump(REVIEW_OUTPUT_SCHEMA, f)
                schema_file = f.name

            # Create output file path (will be written by codex)
            # Use mkstemp for secure temp file creation (avoids TOCTOU race condition)
            fd, output_file = tempfile.mkstemp(suffix=".json")
            os.close(fd)  # Close fd, codex will write to the path

            if ui:
                ui.set_status("starting", "initializing Codex")

            # Build command from config (or use defaults)
            shell_cmd = self._build_command(prompt_file, schema_file, output_file)

            start_time = time.time()

            process = subprocess.Popen(
                shell_cmd,
                shell=True,
                cwd=get_project_root(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout to prevent deadlock
                text=True,
            )

            if ui:
                ui.set_status("running", "Codex reviewing code")
                ui.add_activity("Codex code review started", "🔍")

            # Track timing for progress updates
            last_status_update = start_time
            last_activity_time = start_time
            status_update_interval = 5.0  # Update status every 5 seconds
            activity_interval = 30.0  # Add activity log entry every 30 seconds

            # Poll for completion, checking for pause and timeout
            while True:
                retcode = process.poll()

                if retcode is not None:
                    break

                # Check for pause request
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

                current_time = time.time()
                elapsed = current_time - start_time

                # Check for timeout
                if elapsed > timeout:
                    process.kill()
                    if ui:
                        ui.add_activity(f"Timeout after {timeout}s", "❌")
                    return StageResult.timeout(timeout)

                # Read any available stdout/stderr (non-blocking)
                if process.stdout:
                    try:
                        ready, _, _ = select.select([process.stdout], [], [], 0)
                        if ready:
                            line = process.stdout.readline()
                            if line and ui:
                                # Show meaningful output lines
                                line = line.strip()
                                if line and not line.startswith("{"):  # Skip raw JSON
                                    ui.add_activity(f"codex: {line[:80]}", "💬")
                                    last_activity_time = current_time
                    except (ValueError, TypeError, OSError):
                        # select() may fail on non-selectable streams (e.g., in tests)
                        pass

                # Update status with elapsed time periodically
                if ui and current_time - last_status_update >= status_update_interval:
                    minutes = int(elapsed // 60)
                    seconds = int(elapsed % 60)
                    if minutes > 0:
                        time_str = f"{minutes}m {seconds}s"
                    else:
                        time_str = f"{seconds}s"
                    ui.set_status("running", f"Codex reviewing code ({time_str})")
                    last_status_update = current_time

                # Add periodic activity update if no other activity
                if ui and current_time - last_activity_time >= activity_interval:
                    minutes = int(elapsed // 60)
                    if minutes > 0:
                        ui.add_activity(f"Still reviewing... ({minutes}m elapsed)", "⏳")
                    else:
                        ui.add_activity("Still reviewing...", "⏳")
                    last_activity_time = current_time

                time.sleep(0.5)

            # Capture remaining output for debugging (stderr merged into stdout)
            stdout, _ = process.communicate(timeout=10)

            if process.returncode != 0:
                if ui:
                    ui.add_activity(f"Codex failed (exit {process.returncode})", "❌")
                    ui.finish(success=False)
                return StageResult.error(
                    message=f"Codex failed (exit {process.returncode})",
                    output=stdout,
                )

            # Read the structured output
            if not os.path.exists(output_file):
                if ui:
                    ui.add_activity("No output file generated", "❌")
                    ui.finish(success=False)
                # Include all output for debugging
                debug_output = f"Expected output at: {output_file}\nOutput:\n{stdout}"
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

                # Return success with structured JSON output
                # The workflow will post-process this to write artifacts
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

        finally:
            # Clean up temp files
            for filepath in [prompt_file, schema_file, output_file]:
                if filepath and os.path.exists(filepath):
                    try:
                        os.unlink(filepath)
                    except OSError:
                        pass

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """
        Simple text generation using Codex.

        Note: For simple text generation, we use codex exec without
        structured output schema.
        """
        prompt_file = None
        output_file = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # Use mkstemp for secure temp file creation (avoids TOCTOU race condition)
            fd, output_file = tempfile.mkstemp(suffix=".txt")
            os.close(fd)  # Close fd, codex will write to the path

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

        finally:
            for filepath in [prompt_file, output_file]:
                if filepath and os.path.exists(filepath):
                    try:
                        os.unlink(filepath)
                    except OSError:
                        pass

        return ""
