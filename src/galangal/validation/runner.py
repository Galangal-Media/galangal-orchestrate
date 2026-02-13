"""
Config-driven validation runner.
"""

import fnmatch
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from galangal.config.loader import get_config, get_project_root
from galangal.config.schema import PreflightCheck, SkipCondition, StageValidation, ValidationCommand
from galangal.core.artifacts import (
    artifact_exists,
    read_artifact,
    write_artifact,
    write_skip_artifact,
)
from galangal.core.utils import now_iso, truncate_text


def read_decision_file(stage: str, task_name: str) -> str | None:
    """
    Read a stage decision file and return its normalized content.

    Decision files contain exactly one word indicating the stage result.
    Valid decision values are defined in STAGE_METADATA (state.py).

    Args:
        stage: Stage name (e.g., "SECURITY", "QA", "REVIEW").
        task_name: Name of the task.

    Returns:
        The decision word (uppercase, stripped) or None if file doesn't exist
        or contains invalid content.
    """
    from galangal.core.state import Stage, get_decision_file_name

    try:
        stage_enum = Stage.from_str(stage.upper())
        decision_file = get_decision_file_name(stage_enum)
    except ValueError:
        # Fallback for unknown stages
        decision_file = f"{stage.upper()}_DECISION"

    if not decision_file or not artifact_exists(decision_file, task_name):
        return None

    content = read_artifact(decision_file, task_name)
    if not content:
        return None

    # Strip and normalize - should be exactly one word
    decision = content.strip().upper()

    # Validate it's a single word (no spaces, newlines, etc.)
    if " " in decision or "\n" in decision or len(decision) > 20:
        return None

    return decision


# Decision configurations are now centralized in STAGE_METADATA (state.py)
# Use get_decision_config(stage) to get decision values for a stage


@dataclass
class ValidationResult:
    """
    Result of a validation check.

    Attributes:
        success: Whether the validation passed.
        message: Human-readable description of the result.
        output: Optional detailed output (e.g., test results, command stdout).
        rollback_to: If validation failed, the stage to roll back to (e.g., "DEV").
        skipped: True if the stage was skipped due to skip_if conditions.
        is_fast_track: If True, this is a minor rollback that should skip
            stages that already passed (REQUEST_MINOR_CHANGES).
    """

    success: bool
    message: str
    output: str | None = None
    rollback_to: str | None = None  # Stage to rollback to on failure
    skipped: bool = False  # True if stage was skipped due to conditions
    needs_user_decision: bool = False  # True if decision file missing/unclear
    is_fast_track: bool = False  # True for minor rollbacks (skip passed stages)


def validate_stage_decision(
    stage: str,
    task_name: str,
    artifact_name: str,
    missing_artifact_msg: str | None = None,
    skip_artifact: str | None = None,
) -> ValidationResult:
    """Generic decision file validation for stages.

    This helper consolidates the repeated pattern of:
    1. Check skip artifact
    2. Check decision file for known values
    3. Check if report artifact exists
    4. Request user decision if unclear

    Args:
        stage: Stage name (e.g., "SECURITY", "QA", "REVIEW").
        task_name: Name of the task being validated.
        artifact_name: Name of the report artifact (e.g., "QA_REPORT.md").
        missing_artifact_msg: Custom message if artifact is missing.
        skip_artifact: Optional skip artifact name (e.g., "SECURITY_SKIP.md").

    Returns:
        ValidationResult based on decision file or artifact status.
    """
    from galangal.core.state import Stage, get_decision_config

    stage_upper = stage.upper()

    # Check for skip artifact first
    if skip_artifact and artifact_exists(skip_artifact, task_name):
        return ValidationResult(True, f"{stage_upper} skipped")

    # Check for decision file using centralized config from STAGE_METADATA
    decision = read_decision_file(stage_upper, task_name)
    try:
        stage_enum = Stage.from_str(stage_upper)
        decision_config = get_decision_config(stage_enum) or {}
    except ValueError:
        decision_config = {}

    if decision and decision in decision_config:
        success, message, rollback_to, is_fast_track = decision_config[decision]
        return ValidationResult(
            success, message, rollback_to=rollback_to, is_fast_track=is_fast_track
        )

    # Decision file missing or unclear - check if artifact exists
    if not artifact_exists(artifact_name, task_name):
        msg = missing_artifact_msg or f"{artifact_name} not found"
        return ValidationResult(False, msg, rollback_to="DEV")

    # Artifact exists but no valid decision file - need user to decide
    content = read_artifact(artifact_name, task_name) or ""
    return ValidationResult(
        False,
        f"{stage_upper}_DECISION file missing or unclear - user confirmation required",
        output=content,
        needs_user_decision=True,
    )


class ValidationRunner:
    """
    Config-driven validation runner for workflow stages.

    This class validates stage outputs based on configuration in `.galangal/config.yaml`.
    Each stage can define:
    - `checks`: Preflight checks (path existence, command execution)
    - `commands`: Shell commands to run (e.g., tests, linting)
    - `artifact`/`pass_marker`/`fail_marker`: Artifact content validation
    - `skip_if`: Conditions to skip the stage
    - `artifacts_required`: List of artifacts that must exist

    If no config exists for a stage, default validation logic is used.
    """

    def __init__(self) -> None:
        self.config = get_config()
        self.project_root = get_project_root()

    def validate_stage(
        self,
        stage: str,
        task_name: str,
    ) -> ValidationResult:
        """
        Validate a workflow stage based on config.

        Executes the validation pipeline for a stage:
        1. Check skip conditions (no_files_match, manual skip artifacts)
        2. Run preflight checks (for PREFLIGHT stage)
        3. Run validation commands (all commands run, outputs aggregated)
        4. Check artifact markers (APPROVED, PASS, etc.)
        5. Verify required artifacts exist

        Validation command outputs are aggregated into VALIDATION_REPORT.md
        for easier debugging when failures occur.

        Special handling for:
        - PREFLIGHT: Runs environment checks, generates PREFLIGHT_REPORT.md
        - SECURITY: Checks SECURITY_CHECKLIST.md for APPROVED/REJECTED
        - QA: Checks QA_REPORT.md for Status: PASS/FAIL

        Args:
            stage: The stage name (e.g., "PM", "DEV", "QA").
            task_name: Name of the task being validated.

        Returns:
            ValidationResult indicating success/failure with optional rollback target.
        """
        stage_lower = stage.lower()

        # Get stage validation config
        validation_config = self.config.validation
        stage_config: StageValidation | None = getattr(validation_config, stage_lower, None)

        if stage_config is None:
            # No config for this stage - use defaults
            return self._validate_with_defaults(stage, task_name)

        # NOTE: Skip conditions are checked in get_next_stage() which is the single
        # source of truth for skip logic. By the time we reach validate_stage(),
        # the stage has already been determined to not be skipped.

        # Look up stage metadata for data-driven checks
        from galangal.core.state import STAGE_METADATA, Stage

        try:
            stage_enum = Stage.from_str(stage.upper())
            metadata = STAGE_METADATA.get(stage_enum)
        except ValueError:
            metadata = None

        # Decision-only stages: delegate to decision validation when config exists
        # but the stage is purely decision-driven (no commands/markers configured)
        if metadata and metadata.default_validation == "decision" and metadata.decision_file:
            if not stage_config.commands and not stage_config.artifact:
                artifact_name = metadata.produces_artifacts[0] if metadata.produces_artifacts else f"{stage.upper()}_REPORT.md"
                return validate_stage_decision(
                    stage.upper(),
                    task_name,
                    artifact_name,
                    skip_artifact=metadata.skip_artifact,
                )

        # Run preflight checks (for PREFLIGHT stage)
        if stage_config.checks:
            result = self._run_preflight_checks(stage_config.checks, task_name)
            if not result.success:
                return result

        # Run validation commands and aggregate outputs
        command_results = self._run_all_commands(stage_config, task_name)
        if command_results["has_failure"]:
            # Write validation report with all outputs for debugging
            self._write_validation_report(stage, task_name, command_results)
            return ValidationResult(
                False,
                command_results["first_failure_message"],
                output=command_results["aggregated_output"],
                rollback_to="DEV",
            )

        # Metadata-driven decision/artifact checks after commands pass
        if metadata:
            validation_type = metadata.default_validation

            # Decision-based stages: check decision file
            if validation_type == "decision" and metadata.decision_file:
                artifact_name = metadata.produces_artifacts[0] if metadata.produces_artifacts else f"{stage.upper()}_REPORT.md"
                result = validate_stage_decision(
                    stage.upper(), task_name, artifact_name,
                    skip_artifact=metadata.skip_artifact,
                )
                if result.success or result.rollback_to:
                    return result

            # Decision-or-markers: try decision, fall through to artifact markers
            if validation_type == "decision_or_markers" and metadata.decision_file:
                artifact_name = metadata.produces_artifacts[0] if metadata.produces_artifacts else f"{stage.upper()}_REPORT.md"
                result = validate_stage_decision(stage.upper(), task_name, artifact_name)
                if result.success or result.rollback_to:
                    return result
                # Fall through to artifact marker check

            # Artifact-only stages: check required artifacts exist
            if validation_type == "artifacts":
                required = metadata.required_artifacts or metadata.produces_artifacts
                for art_name in required:
                    if not artifact_exists(art_name, task_name):
                        return ValidationResult(False, f"{art_name} not found")
                if required and not stage_config.artifact:
                    return ValidationResult(True, f"{stage} validation passed")

        # Check for pass/fail markers in artifacts (fallback for AI-driven stages)
        if stage_config.artifact and stage_config.pass_marker:
            result = self._check_artifact_markers(stage_config, task_name)
            if not result.success:
                return result

        # Check required artifacts
        for artifact_name in stage_config.artifacts_required:
            if not artifact_exists(artifact_name, task_name):
                return ValidationResult(
                    False,
                    f"{artifact_name} not found",
                    rollback_to="DEV",
                )

        # Validate artifact schemas if enabled
        schema_result = self._validate_artifact_schemas(stage, task_name)
        if schema_result and not schema_result.success:
            return schema_result

        return ValidationResult(True, f"{stage} validation passed")

    def _get_all_changed_files(self) -> set[str]:
        """
        Get all changed files from commits, staging area, and working tree.

        Collects files from multiple sources to ensure skip detection works
        correctly even in dirty working trees:

        1. Committed changes: `git diff --name-only base_branch...HEAD`
        2. Working tree changes: `git status --porcelain` (staged, unstaged, untracked)

        Returns:
            Set of file paths that have been changed, staged, or are untracked.
            Empty set on error.
        """
        changed: set[str] = set()

        try:
            # 1. Committed changes vs base branch
            base_branch = self.config.pr.base_branch
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                changed.update(f for f in result.stdout.strip().split("\n") if f)

            # 2. Working tree changes (staged, unstaged, untracked)
            # Porcelain format: "XY filename" or "XY old -> new" for renames
            # X = staging area status, Y = working tree status
            # ?? = untracked, M = modified, A = added, D = deleted, R = renamed
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    if line and len(line) >= 3:
                        # Extract filename (handle renames: "R  old -> new")
                        file_part = line[3:]
                        if " -> " in file_part:
                            # For renames, include both old and new paths
                            old, new = file_part.split(" -> ", 1)
                            changed.add(old)
                            changed.add(new)
                        else:
                            changed.add(file_part)

        except Exception:
            pass  # Return whatever we collected so far

        return changed

    def _should_skip(self, skip_condition: SkipCondition, task_name: str) -> bool:
        """
        Check if a stage's skip condition is met.

        Supports `no_files_match` condition which checks if any changed files
        match the given glob patterns. Changed files include:
        - Committed changes vs base branch
        - Staged changes (git add)
        - Unstaged changes (modified tracked files)
        - Untracked files (new files not yet added)

        This ensures conditional stages are not incorrectly skipped when
        relevant files exist in the working tree but haven't been committed.

        Args:
            skip_condition: Config object with skip criteria (e.g., no_files_match).
            task_name: Name of the task (unused, for future conditions).

        Returns:
            True if the stage should be skipped, False otherwise.
        """
        if skip_condition.no_files_match:
            try:
                changed_files = self._get_all_changed_files()

                # If we couldn't get any file info, don't skip (safe default)
                if not changed_files:
                    return False

                # Support both single pattern and list of patterns
                patterns = skip_condition.no_files_match
                if isinstance(patterns, str):
                    patterns = [patterns]

                for f in changed_files:
                    for pattern in patterns:
                        if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(
                            f.lower(), pattern.lower()
                        ):
                            return False  # Found a match, don't skip

                return True  # No matches, skip
            except Exception:
                return False  # On error, don't skip

        return False

    def _write_skip_artifact(self, stage: str, task_name: str, reason: str) -> None:
        """Write a skip marker artifact."""
        write_skip_artifact(stage, reason, task_name)

    def should_skip_stage(self, stage: str, task_name: str) -> bool:
        """
        Check if a stage should be skipped based on skip_if conditions only.

        This method checks ONLY the skip_if condition configured for a stage,
        without running any validation commands. Use this when you need to
        determine whether to skip a conditional stage before execution.

        Args:
            stage: The stage name (e.g., "MIGRATION", "CONTRACT", "BENCHMARK").
            task_name: Name of the task (for future conditions).

        Returns:
            True if the stage should be skipped, False otherwise.
        """
        stage_lower = stage.lower()
        validation_config = self.config.validation
        stage_config: StageValidation | None = getattr(validation_config, stage_lower, None)

        if stage_config is None:
            return False

        if stage_config.skip_if:
            return self._should_skip(stage_config.skip_if, task_name)

        return False

    def _run_preflight_checks(
        self, checks: list[PreflightCheck], task_name: str
    ) -> ValidationResult:
        """
        Run preflight environment checks and generate PREFLIGHT_REPORT.md.

        Preflight checks verify the development environment is ready:
        - Path existence checks (e.g., config files, virtual envs)
        - Command execution checks (e.g., git status, tool versions)

        Each check can be:
        - Required: Failure stops the workflow
        - warn_only: Failure logs a warning but continues

        The function generates PREFLIGHT_REPORT.md with detailed results
        for each check.

        Args:
            checks: List of PreflightCheck configs to run.
            task_name: Task name for writing the report artifact.

        Returns:
            ValidationResult with success=True if all required checks pass.
            Output contains the generated report content.
        """
        results: dict[str, dict[str, str]] = {}
        all_ok = True

        for check in checks:
            if check.path_exists:
                path = self.project_root / check.path_exists
                exists = path.exists()
                results[check.name] = {"status": "OK" if exists else "Missing"}
                if not exists and not check.warn_only:
                    all_ok = False

            elif check.command:
                try:
                    # Support both string (shell) and list (direct) commands
                    if isinstance(check.command, list):
                        result = subprocess.run(
                            check.command,
                            shell=False,
                            cwd=self.project_root,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                    else:
                        result = subprocess.run(
                            check.command,
                            shell=True,
                            cwd=self.project_root,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                    output = result.stdout.strip()

                    if check.expect_empty:
                        # Filter out task-related files for git status
                        if output:
                            filtered = self._filter_task_files(output, task_name)
                            ok = not filtered
                        else:
                            ok = True
                    else:
                        ok = result.returncode == 0

                    status = "OK" if ok else ("Warning" if check.warn_only else "Failed")
                    results[check.name] = {
                        "status": status,
                        "output": output[:200] if output else "",
                    }
                    if not ok and not check.warn_only:
                        all_ok = False

                except Exception as e:
                    results[check.name] = {"status": "Error", "error": str(e)}
                    if not check.warn_only:
                        all_ok = False

        # Generate report (uses now_iso imported at module level)
        status = "READY" if all_ok else "NOT_READY"
        report = f"""# Preflight Report

## Summary
- **Status:** {status}
- **Date:** {now_iso()}

## Checks
"""
        for name, check_result in results.items():
            status_val = check_result.get("status", "Unknown")
            if status_val == "OK":
                status_icon = "✓"
            elif status_val == "Warning":
                status_icon = "⚠"
            else:
                status_icon = "✗"
            report += f"\n### {status_icon} {name}\n"
            report += f"- Status: {check_result.get('status', 'Unknown')}\n"
            if check_result.get("output"):
                report += f"- Output: {check_result['output']}\n"
            if check_result.get("error"):
                report += f"- Error: {check_result['error']}\n"

        write_artifact("PREFLIGHT_REPORT.md", report, task_name)

        if all_ok:
            return ValidationResult(True, "Preflight checks passed", output=report)
        return ValidationResult(
            False,
            "Preflight checks failed - fix environment issues",
            output=report,
        )

    def _filter_task_files(self, git_status: str, task_name: str) -> str:
        """Filter out task-related files from git status output."""
        config = get_config()
        tasks_dir = config.tasks_dir

        filtered_lines = []
        for line in git_status.split("\n"):
            file_path = line[3:] if len(line) > 3 else line
            # Skip task artifacts directory
            if file_path.startswith(f"{tasks_dir}/"):
                continue
            filtered_lines.append(line)

        return "\n".join(filtered_lines)

    def _get_placeholders(self, task_name: str) -> dict[str, str]:
        """
        Build placeholder substitution dictionary for commands.

        Returns:
            Dict mapping placeholder names to their values:
            - {task_dir}: Full path to task directory
            - {project_root}: Full path to project root
            - {base_branch}: Configured base branch name
        """
        config = get_config()
        return {
            "{task_dir}": str(self.project_root / config.tasks_dir / task_name),
            "{project_root}": str(self.project_root),
            "{base_branch}": config.pr.base_branch,
        }

    def _substitute_placeholders(self, text: str, placeholders: dict[str, str]) -> str:
        """Substitute all placeholders in a string."""
        for key, value in placeholders.items():
            text = text.replace(key, value)
        return text

    def _run_command(
        self, cmd_config: ValidationCommand, task_name: str, default_timeout: int
    ) -> ValidationResult:
        """
        Execute a validation command and return the result.

        Commands can be specified as:
        - String: Executed via shell (supports &&, |, etc.)
        - List: Executed directly without shell (safer for paths with spaces)

        Supported placeholders: {task_dir}, {project_root}, {base_branch}

        Args:
            cmd_config: Command configuration with name, command (str or list),
                timeout, and optional/allow_failure flags.
            task_name: Task name for placeholder substitution.
            default_timeout: Timeout to use if not specified in config.

        Returns:
            ValidationResult with success based on exit code.
            Failure results include rollback_to="DEV".
        """
        placeholders = self._get_placeholders(task_name)
        timeout = cmd_config.timeout if cmd_config.timeout is not None else default_timeout

        try:
            if isinstance(cmd_config.command, list):
                # List form: substitute placeholders in each element, run without shell
                cmd = [
                    self._substitute_placeholders(arg, placeholders) for arg in cmd_config.command
                ]
                result = subprocess.run(
                    cmd,
                    shell=False,
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                # String form: substitute and run via shell (backwards compatible)
                command = self._substitute_placeholders(cmd_config.command, placeholders)
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

            if result.returncode == 0:
                return ValidationResult(
                    True,
                    f"{cmd_config.name}: passed",
                    output=result.stdout,
                )
            else:
                return ValidationResult(
                    False,
                    f"{cmd_config.name}: failed",
                    output=result.stdout + result.stderr,
                    rollback_to="DEV",
                )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                False,
                f"{cmd_config.name}: timed out",
                rollback_to="DEV",
            )
        except Exception as e:
            return ValidationResult(
                False,
                f"{cmd_config.name}: error - {e}",
                rollback_to="DEV",
            )

    def _run_all_commands(self, stage_config: StageValidation, task_name: str) -> dict[str, Any]:
        """
        Run all validation commands and aggregate their outputs.

        Unlike early-return behavior, this runs ALL commands to collect
        complete debugging information when failures occur.

        Args:
            stage_config: Stage validation configuration with commands list.
            task_name: Task name for placeholder substitution.

        Returns:
            Dict with:
            - has_failure: True if any non-optional command failed
            - first_failure_message: Message from first failing command
            - aggregated_output: Combined output from all commands
            - results: List of (name, success, output) tuples
        """
        results: list[tuple[str, bool, str]] = []
        has_failure = False
        first_failure_message = ""

        for cmd_config in stage_config.commands:
            result = self._run_command(cmd_config, task_name, stage_config.timeout)
            output = result.output or ""
            results.append((cmd_config.name, result.success, output))

            if not result.success:
                if cmd_config.optional:
                    continue
                if cmd_config.allow_failure:
                    continue
                if not has_failure:
                    has_failure = True
                    first_failure_message = result.message

        # Build aggregated output for debugging
        aggregated_parts = []
        for name, success, output in results:
            status = "✓ PASSED" if success else "✗ FAILED"
            aggregated_parts.append(f"=== {name}: {status} ===")
            if output:
                aggregated_parts.append(output.strip())
            aggregated_parts.append("")

        # Build command config lookup by name
        cmd_configs = {cmd.name: cmd for cmd in stage_config.commands}

        return {
            "has_failure": has_failure,
            "first_failure_message": first_failure_message,
            "aggregated_output": "\n".join(aggregated_parts),
            "results": results,
            "command_configs": cmd_configs,
        }

    def _write_validation_report(
        self, stage: str, task_name: str, command_results: dict[str, Any]
    ) -> None:
        """
        Write VALIDATION_REPORT.md with aggregated command outputs.

        Creates a structured report showing all validation command results,
        making it easier to debug failures without re-running commands.

        Args:
            stage: Stage name (e.g., "TEST", "QA").
            task_name: Task name for artifact path.
            command_results: Results from _run_all_commands().
        """
        from datetime import datetime

        lines = [
            f"# {stage} Validation Report",
            "",
            f"**Generated:** {datetime.now().isoformat()}",
            "",
            "## Summary",
            "",
        ]

        passed = sum(1 for _, success, _ in command_results["results"] if success)
        failed = len(command_results["results"]) - passed
        lines.append(f"- **Passed:** {passed}")
        lines.append(f"- **Failed:** {failed}")
        lines.append("")
        lines.append("## Command Results")
        lines.append("")

        for name, success, output in command_results["results"]:
            status = "✓ PASSED" if success else "✗ FAILED"
            lines.append(f"### {name}: {status}")
            lines.append("")
            if output:
                # Truncate very long outputs
                truncated = output[:5000]
                if len(output) > 5000:
                    truncated += "\n\n... (output truncated)"
                lines.append("```")
                lines.append(truncated.strip())
                lines.append("```")
            else:
                lines.append("_(no output)_")
            lines.append("")

        report_content = "\n".join(lines)
        write_artifact("VALIDATION_REPORT.md", report_content, task_name)

        # Write concise test summary for stages that have write_test_summary=True
        from galangal.core.state import STAGE_METADATA, Stage

        try:
            stage_enum = Stage.from_str(stage.upper())
            metadata = STAGE_METADATA.get(stage_enum)
            if metadata and metadata.write_test_summary:
                self._write_test_summary(task_name, command_results)
        except ValueError:
            pass

    def _write_test_summary(self, task_name: str, command_results: dict[str, Any]) -> None:
        """
        Write TEST_SUMMARY.md with concise test results for downstream prompts.

        Parses test output to extract key information without verbose logs.
        Supports pytest output format primarily.

        Args:
            task_name: Task name for artifact path.
            command_results: Results from _run_all_commands().
        """
        from datetime import datetime

        # Find test command output (look for pytest, jest, etc.)
        test_output = ""
        test_cmd_name = ""
        for name, success, output in command_results["results"]:
            name_lower = name.lower()
            if any(kw in name_lower for kw in ["test", "pytest", "jest", "mocha", "unittest"]):
                test_output = output
                test_cmd_name = name
                break

        # If no specific test command found, use all output
        if not test_output:
            test_output = command_results.get("aggregated_output", "")
            test_cmd_name = "tests"

        # Try JUnit XML first, fall back to stdout parsing
        cmd_configs = command_results.get("command_configs", {})
        cmd_config = cmd_configs.get(test_cmd_name)
        xml_summary = self._try_parse_junit_xml(task_name, cmd_config)

        if xml_summary.get("counts"):
            summary = xml_summary
            # Merge coverage and warnings from stdout (JUnit XML doesn't have these)
            stdout_summary = self._parse_test_output(test_output)
            if stdout_summary["coverage"] and not summary["coverage"]:
                summary["coverage"] = stdout_summary["coverage"]
            if stdout_summary["warnings"] and not summary["warnings"]:
                summary["warnings"] = stdout_summary["warnings"]
        else:
            summary = self._parse_test_output(test_output)

        # Determine overall status
        has_failure = command_results.get("has_failure", False)
        status = "FAIL" if has_failure else "PASS"

        lines = [
            "# Test Summary",
            "",
            f"**Status:** {status}",
            f"**Command:** {test_cmd_name}",
            f"**Generated:** {datetime.now().isoformat()}",
            "",
        ]

        # Add counts if parsed
        if summary["counts"]:
            lines.append(summary["counts"])
            lines.append("")

        # Add duration if found
        if summary["duration"]:
            lines.append(f"**Duration:** {summary['duration']}")
            lines.append("")

        # Add failed tests
        if summary["failed_tests"]:
            lines.append("## Failed Tests")
            lines.append("")
            for test_info in summary["failed_tests"][:20]:  # Limit to 20 failures
                lines.append(f"- {test_info}")
            if len(summary["failed_tests"]) > 20:
                lines.append(f"- ... and {len(summary['failed_tests']) - 20} more failures")
            lines.append("")

        # Add coverage if found
        if summary["coverage"]:
            lines.append("## Coverage")
            lines.append("")
            lines.append(summary["coverage"])
            lines.append("")

        # Add warnings/errors summary (not full output)
        if summary["warnings"]:
            lines.append("## Warnings")
            lines.append("")
            for warning in summary["warnings"][:10]:
                lines.append(f"- {warning}")
            lines.append("")

        write_artifact("TEST_SUMMARY.md", "\n".join(lines), task_name)

    def _parse_test_output(self, output: str) -> dict[str, Any]:
        """
        Parse test output to extract summary information.

        Supports pytest output format. Returns structured summary data.

        Args:
            output: Raw test command output.

        Returns:
            Dict with counts, duration, failed_tests, coverage, warnings.
        """
        import re

        result: dict[str, Any] = {
            "counts": "",
            "duration": "",
            "failed_tests": [],
            "coverage": "",
            "warnings": [],
        }

        if not output:
            return result

        lines = output.split("\n")

        # Parse pytest-style summary line: "5 passed, 2 failed, 1 skipped in 3.45s"
        for line in lines:
            # Match pytest summary
            summary_match = re.search(
                r"(\d+)\s+passed.*?(\d+)\s+failed|(\d+)\s+passed",
                line,
                re.IGNORECASE,
            )
            if summary_match:
                result["counts"] = line.strip()

            # Match duration
            duration_match = re.search(r"in\s+([\d.]+)s", line)
            if duration_match:
                result["duration"] = f"{duration_match.group(1)}s"

            # Match pytest short summary (=== short test summary info ===)
            # or individual FAILED lines
            if "FAILED" in line:
                # Extract test name and brief error
                failed_match = re.match(r"FAILED\s+(\S+)(?:\s+-\s+(.+))?", line.strip())
                if failed_match:
                    test_name = failed_match.group(1)
                    error_brief = failed_match.group(2) or ""
                    if error_brief:
                        result["failed_tests"].append(f"`{test_name}` - {error_brief[:100]}")
                    else:
                        result["failed_tests"].append(f"`{test_name}`")

            # Match coverage summary
            if "TOTAL" in line and "%" in line:
                result["coverage"] = line.strip()
            elif re.match(r"^(Lines|Branches|Coverage):\s*\d+%", line.strip()):
                result["coverage"] += line.strip() + "\n"

            # Collect warnings (pytest warnings summary)
            if "warning" in line.lower() and "PytestWarning" not in line:
                warning_text = line.strip()[:150]
                if warning_text and warning_text not in result["warnings"]:
                    result["warnings"].append(warning_text)

        # Also look for assertion errors in failed test output
        if not result["failed_tests"]:
            # Try to find test failures from assertion errors
            for i, line in enumerate(lines):
                if "AssertionError" in line or "Error:" in line:
                    # Look backwards for test name
                    for j in range(max(0, i - 5), i):
                        test_match = re.search(r"(test_\w+)", lines[j])
                        if test_match:
                            error_brief = line.strip()[:80]
                            test_entry = f"`{test_match.group(1)}` - {error_brief}"
                            if test_entry not in result["failed_tests"]:
                                result["failed_tests"].append(test_entry)
                            break

        return result

    def _parse_junit_xml(self, xml_path: Path) -> dict[str, Any]:
        """
        Parse a JUnit XML file and return structured test summary data.

        Handles both ``<testsuites>`` root with multiple ``<testsuite>`` children
        and a single ``<testsuite>`` root element.

        Args:
            xml_path: Path to the JUnit XML file.

        Returns:
            Dict with counts, duration, failed_tests, coverage, warnings.
            Returns empty result on any parse error.
        """
        result: dict[str, Any] = {
            "counts": "",
            "duration": "",
            "failed_tests": [],
            "coverage": "",
            "warnings": [],
        }

        try:
            tree = ET.parse(xml_path)  # noqa: S314
            root = tree.getroot()

            # Collect all <testsuite> elements
            if root.tag == "testsuites":
                suites = list(root.iter("testsuite"))
            elif root.tag == "testsuite":
                suites = [root]
            else:
                return result

            total_tests = 0
            total_failures = 0
            total_errors = 0
            total_skipped = 0
            total_time = 0.0

            for suite in suites:
                total_tests += int(suite.get("tests", 0))
                total_failures += int(suite.get("failures", 0))
                total_errors += int(suite.get("errors", 0))
                total_skipped += int(suite.get("skipped", 0))
                total_time += float(suite.get("time", 0))

            # Build counts string
            passed = total_tests - total_failures - total_errors - total_skipped
            parts = [f"{passed} passed"]
            if total_failures:
                parts.append(f"{total_failures} failed")
            if total_errors:
                parts.append(f"{total_errors} errors")
            if total_skipped:
                parts.append(f"{total_skipped} skipped")
            result["counts"] = ", ".join(parts)
            result["duration"] = f"{total_time:.2f}s"

            # Extract failed test details
            for testcase in root.iter("testcase"):
                classname = testcase.get("classname", "")
                name = testcase.get("name", "")
                test_id = f"{classname}::{name}" if classname else name

                for child in testcase:
                    if child.tag in ("failure", "error"):
                        message = child.get("message", "")
                        brief = message[:100] if message else child.tag
                        result["failed_tests"].append(f"`{test_id}` - {brief}")

        except Exception:
            pass  # Return empty result on any error

        return result

    def _try_parse_junit_xml(
        self,
        task_name: str,
        cmd_config: ValidationCommand | None = None,
    ) -> dict[str, Any]:
        """
        Try to find and parse a JUnit XML file for test results.

        Resolution order:
        1. Explicit config: ``cmd_config.junit_xml`` with placeholder substitution
        2. Convention: ``{task_dir}/junit.xml``

        Args:
            task_name: Task name for placeholder substitution and convention path.
            cmd_config: Optional command config with ``junit_xml`` path.

        Returns:
            Parsed test summary dict, or empty result if no XML found.
        """
        empty: dict[str, Any] = {
            "counts": "",
            "duration": "",
            "failed_tests": [],
            "coverage": "",
            "warnings": [],
        }

        placeholders = self._get_placeholders(task_name)

        # Strategy 1: Explicit config path
        if cmd_config and cmd_config.junit_xml:
            resolved = self._substitute_placeholders(cmd_config.junit_xml, placeholders)
            xml_path = Path(resolved)
            if xml_path.is_file():
                return self._parse_junit_xml(xml_path)

        # Strategy 2: Convention path
        from galangal.core.state import get_task_dir

        convention_path = get_task_dir(task_name) / "junit.xml"
        if convention_path.is_file():
            return self._parse_junit_xml(convention_path)

        return empty

    def _check_artifact_markers(
        self, stage_config: StageValidation, task_name: str
    ) -> ValidationResult:
        """Check for pass/fail markers in an artifact."""
        artifact_name = stage_config.artifact
        if not artifact_name:
            return ValidationResult(True, "No artifact to check")

        content = read_artifact(artifact_name, task_name)
        if not content:
            return ValidationResult(
                False,
                f"{artifact_name} not found or empty",
                rollback_to="DEV",
            )

        content_upper = content.upper()

        if stage_config.pass_marker and stage_config.pass_marker in content_upper:
            return ValidationResult(True, f"{artifact_name}: approved")

        if stage_config.fail_marker and stage_config.fail_marker in content_upper:
            return ValidationResult(
                False,
                f"{artifact_name}: changes requested",
                rollback_to="DEV",
            )

        # Markers unclear - prompt user to decide instead of retry loop
        return ValidationResult(
            False,
            f"{artifact_name}: unclear result - must contain {stage_config.pass_marker} or {stage_config.fail_marker}",
            output=truncate_text(content, 2000),
            needs_user_decision=True,
        )

    def _validate_artifact_schemas(self, stage: str, task_name: str) -> ValidationResult | None:
        """
        Validate artifacts produced by this stage against their schemas.

        Only validates if schema validation is enabled in config and schemas
        are defined for the stage's artifacts.

        Args:
            stage: Stage name that produced the artifacts.
            task_name: Task name for artifact lookups.

        Returns:
            ValidationResult with schema errors, or None if validation passed/skipped.
        """
        # Check if schema validation is enabled
        if not getattr(self.config, "schema_validation_enabled", True):
            return None

        from galangal.core.state import STAGE_METADATA, Stage, load_state
        from galangal.schemas import ArtifactSchemaValidator

        # Get artifacts produced by this stage
        try:
            stage_enum = Stage.from_str(stage.upper())
            metadata = STAGE_METADATA.get(stage_enum)
            if not metadata:
                return None
            artifacts_produced = metadata.produces_artifacts
        except ValueError:
            return None

        if not artifacts_produced:
            return None

        # Get task type for schema overrides
        state = load_state(task_name)
        task_type = state.task_type.value if state else "feature"

        # Validate each artifact
        validator = ArtifactSchemaValidator()
        all_errors: list[str] = []
        all_warnings: list[str] = []

        for artifact_name in artifacts_produced:
            content = read_artifact(artifact_name, task_name)
            if not content:
                continue  # Missing artifacts handled by artifacts_required check

            result = validator.validate(artifact_name, content, task_type)

            if result.errors:
                all_errors.extend(result.errors)
            if result.warnings:
                all_warnings.extend(result.warnings)

        if all_errors:
            # Build feedback message
            feedback = "Schema validation failed:\n"
            for error in all_errors:
                feedback += f"  - {error}\n"
            if all_warnings:
                feedback += "\nWarnings:\n"
                for warning in all_warnings:
                    feedback += f"  - {warning}\n"
            feedback += "\nPlease revise the artifact(s) to include the required sections."

            return ValidationResult(
                False,
                "Artifact schema validation failed",
                output=feedback,
                rollback_to=None,  # Retry same stage, don't rollback
            )

        return None  # Validation passed

    def _validate_with_defaults(self, stage: str, task_name: str) -> ValidationResult:
        """
        Validate a stage using metadata-driven default logic.

        Used when no validation config exists for a stage. Looks up
        StageMetadata.default_validation to determine the strategy:
        - "always_pass" / "none": Always succeed
        - "decision": Check decision file via validate_stage_decision()
        - "decision_or_markers": Try decision file, fall through to artifact check
        - "artifacts": Check required_artifacts (or produces_artifacts) exist

        Args:
            stage: The stage name (case-insensitive).
            task_name: Task name for artifact lookups.

        Returns:
            ValidationResult based on metadata-driven defaults.
        """
        from galangal.core.state import STAGE_METADATA, Stage

        stage_upper = stage.upper()

        # Look up stage metadata
        try:
            stage_enum = Stage.from_str(stage_upper)
            metadata = STAGE_METADATA.get(stage_enum)
        except ValueError:
            metadata = None

        if not metadata:
            return ValidationResult(True, f"{stage} completed")

        # Check skip artifact first
        if metadata.skip_artifact and artifact_exists(metadata.skip_artifact, task_name):
            return ValidationResult(True, f"{stage_upper} skipped")

        validation_type = metadata.default_validation

        # Always-pass and no-op stages
        if validation_type in ("always_pass", "none"):
            return ValidationResult(True, f"{stage_upper} completed")

        # Decision-based validation
        if validation_type == "decision":
            artifact_name = metadata.produces_artifacts[0] if metadata.produces_artifacts else f"{stage_upper}_REPORT.md"
            return validate_stage_decision(
                stage_upper,
                task_name,
                artifact_name,
                skip_artifact=metadata.skip_artifact,
            )

        # Decision-or-markers: try decision first, fall through to artifacts
        if validation_type == "decision_or_markers":
            artifact_name = metadata.produces_artifacts[0] if metadata.produces_artifacts else f"{stage_upper}_REPORT.md"
            result = validate_stage_decision(stage_upper, task_name, artifact_name)
            if result.success or result.rollback_to:
                return result
            # Fall through to artifact check

        # Artifact-based validation (also fallback for decision_or_markers)
        required = metadata.required_artifacts or metadata.produces_artifacts
        for artifact_name in required:
            if not artifact_exists(artifact_name, task_name):
                return ValidationResult(False, f"{artifact_name} not found")

        return ValidationResult(True, f"{stage_upper} stage validated")
