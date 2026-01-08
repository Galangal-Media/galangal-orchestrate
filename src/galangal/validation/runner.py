"""
Config-driven validation runner.
"""

import fnmatch
import re
import subprocess
from dataclasses import dataclass

from galangal.config.loader import get_config, get_project_root
from galangal.config.schema import PreflightCheck, StageValidation, ValidationCommand
from galangal.core.artifacts import artifact_exists, read_artifact, write_artifact


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
    """

    success: bool
    message: str
    output: str | None = None
    rollback_to: str | None = None  # Stage to rollback to on failure
    skipped: bool = False  # True if stage was skipped due to conditions


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

    def __init__(self):
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
        3. Run validation commands
        4. Check artifact markers (APPROVED, PASS, etc.)
        5. Verify required artifacts exist

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
        stage_config: StageValidation | None = getattr(
            validation_config, stage_lower, None
        )

        if stage_config is None:
            # No config for this stage - use defaults
            return self._validate_with_defaults(stage, task_name)

        # Check skip conditions
        if stage_config.skip_if:
            if self._should_skip(stage_config.skip_if, task_name):
                self._write_skip_artifact(stage, task_name, "Condition met")
                return ValidationResult(True, f"{stage} skipped (condition met)", skipped=True)

        # SECURITY stage: if checklist says APPROVED, skip validation commands
        # (the AI has already run scans and documented waivers)
        if stage_lower == "security":
            if artifact_exists("SECURITY_CHECKLIST.md", task_name):
                checklist = read_artifact("SECURITY_CHECKLIST.md", task_name) or ""
                if "APPROVED" in checklist.upper():
                    return ValidationResult(True, "Security review approved")
                if "REJECTED" in checklist.upper() or "BLOCKED" in checklist.upper():
                    return ValidationResult(
                        False, "Security review found blocking issues", rollback_to="DEV"
                    )

        # Run preflight checks (for PREFLIGHT stage)
        if stage_config.checks:
            result = self._run_preflight_checks(stage_config.checks, task_name)
            if not result.success:
                return result

        # Run validation commands
        for cmd_config in stage_config.commands:
            result = self._run_command(cmd_config, task_name, stage_config.timeout)
            if not result.success:
                if cmd_config.optional:
                    continue
                if cmd_config.allow_failure:
                    # Log but don't fail
                    continue
                return result

        # Check for pass/fail markers in artifacts (for AI-driven stages)
        if stage_config.artifact and stage_config.pass_marker:
            result = self._check_artifact_markers(stage_config, task_name)
            if not result.success:
                return result

        # QA stage: always check QA_REPORT.md for PASS/FAIL status
        if stage_lower == "qa":
            result = self._check_qa_report(task_name)
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

        return ValidationResult(True, f"{stage} validation passed")

    def _should_skip(self, skip_condition, task_name: str) -> bool:
        """
        Check if a stage's skip condition is met.

        Currently supports `no_files_match` condition which checks if any files
        in `git diff main...HEAD` match the given glob patterns. If no files
        match, the stage should be skipped.

        Args:
            skip_condition: Config object with skip criteria (e.g., no_files_match).
            task_name: Name of the task (unused, for future conditions).

        Returns:
            True if the stage should be skipped, False otherwise.
        """
        if skip_condition.no_files_match:
            # Check if any files match the glob pattern(s) in git diff
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "main...HEAD"],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                changed_files = result.stdout.strip().split("\n")

                # Support both single pattern and list of patterns
                patterns = skip_condition.no_files_match
                if isinstance(patterns, str):
                    patterns = [patterns]

                for f in changed_files:
                    for pattern in patterns:
                        if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(f.lower(), pattern.lower()):
                            return False  # Found a match, don't skip

                return True  # No matches, skip
            except Exception:
                return False  # On error, don't skip

        return False

    def _write_skip_artifact(self, stage: str, task_name: str, reason: str) -> None:
        """Write a skip marker artifact."""
        from datetime import datetime, timezone

        content = f"""# {stage} Stage Skipped

Date: {datetime.now(timezone.utc).isoformat()}
Reason: {reason}
"""
        write_artifact(f"{stage.upper()}_SKIP.md", content, task_name)

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
        from datetime import datetime, timezone

        results: dict[str, dict] = {}
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

        # Generate report
        status = "READY" if all_ok else "NOT_READY"
        report = f"""# Preflight Report

## Summary
- **Status:** {status}
- **Date:** {datetime.now(timezone.utc).isoformat()}

## Checks
"""
        for name, result in results.items():
            status_val = result.get("status", "Unknown")
            if status_val == "OK":
                status_icon = "✓"
            elif status_val == "Warning":
                status_icon = "⚠"
            else:
                status_icon = "✗"
            report += f"\n### {status_icon} {name}\n"
            report += f"- Status: {result.get('status', 'Unknown')}\n"
            if result.get("output"):
                report += f"- Output: {result['output']}\n"
            if result.get("error"):
                report += f"- Error: {result['error']}\n"

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

    def _run_command(
        self, cmd_config: ValidationCommand, task_name: str, default_timeout: int
    ) -> ValidationResult:
        """
        Execute a validation command and return the result.

        Runs a shell command (e.g., pytest, ruff check) and interprets the
        exit code to determine success. The command can use `{task_dir}`
        placeholder which is replaced with the task's directory path.

        Args:
            cmd_config: Command configuration with name, command string,
                timeout, and optional/allow_failure flags.
            task_name: Task name for {task_dir} substitution.
            default_timeout: Timeout to use if not specified in config.

        Returns:
            ValidationResult with success based on exit code.
            Failure results include rollback_to="DEV".
        """
        command = cmd_config.command.replace("{task_dir}", str(get_project_root() / get_config().tasks_dir / task_name))
        timeout = cmd_config.timeout if cmd_config.timeout is not None else default_timeout

        try:
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

        return ValidationResult(
            False,
            f"{artifact_name}: unclear result - must contain {stage_config.pass_marker} or {stage_config.fail_marker}",
        )

    def _check_qa_report(self, task_name: str) -> ValidationResult:
        """Check QA_REPORT.md for pass/fail status.

        Looks for **Status:** PASS or **Status:** FAIL pattern,
        which is more reliable than searching for PASS/FAIL anywhere in content.
        """
        if not artifact_exists("QA_REPORT.md", task_name):
            return ValidationResult(False, "QA_REPORT.md not found", rollback_to="DEV")

        content = read_artifact("QA_REPORT.md", task_name) or ""
        content_upper = content.upper()

        # Look for explicit status line pattern: **Status:** PASS or FAIL
        status_match = re.search(r"\*\*STATUS:\*\*\s*(PASS|FAIL)", content_upper)

        if status_match:
            status = status_match.group(1)
            if status == "PASS":
                return ValidationResult(True, "QA report: PASS")
            else:
                return ValidationResult(False, "QA report: FAIL", rollback_to="DEV")

        # Fallback: check for Status: PASS/FAIL without markdown
        status_match = re.search(r"STATUS:\s*(PASS|FAIL)", content_upper)
        if status_match:
            status = status_match.group(1)
            if status == "PASS":
                return ValidationResult(True, "QA report: PASS")
            else:
                return ValidationResult(False, "QA report: FAIL", rollback_to="DEV")

        # If no clear status found, report as unclear
        return ValidationResult(
            False,
            "QA_REPORT.md: No clear status found - must contain '**Status:** PASS' or '**Status:** FAIL'",
            rollback_to="DEV",
        )

    def _validate_with_defaults(
        self, stage: str, task_name: str
    ) -> ValidationResult:
        """
        Validate a stage using built-in default logic.

        Used when no validation config exists for a stage. Implements
        sensible defaults for each stage:
        - PM: Requires SPEC.md and PLAN.md
        - DESIGN: Requires DESIGN.md or DESIGN_SKIP.md
        - DEV: Always passes (QA will validate)
        - TEST: Requires TEST_PLAN.md
        - QA: Checks QA_REPORT.md for PASS/FAIL
        - SECURITY: Checks SECURITY_CHECKLIST.md for APPROVED/REJECTED
        - REVIEW: Checks REVIEW_NOTES.md for APPROVE/REQUEST_CHANGES
        - DOCS: Requires DOCS_REPORT.md

        Args:
            stage: The stage name (case-insensitive).
            task_name: Task name for artifact lookups.

        Returns:
            ValidationResult based on stage-specific defaults.
        """
        stage_upper = stage.upper()

        # PM stage - check for SPEC.md and PLAN.md
        if stage_upper == "PM":
            if not artifact_exists("SPEC.md", task_name):
                return ValidationResult(False, "SPEC.md not found")
            if not artifact_exists("PLAN.md", task_name):
                return ValidationResult(False, "PLAN.md not found")
            return ValidationResult(True, "PM stage validated")

        # DESIGN stage - check for DESIGN.md or skip marker
        if stage_upper == "DESIGN":
            if artifact_exists("DESIGN_SKIP.md", task_name):
                return ValidationResult(True, "Design skipped")
            if not artifact_exists("DESIGN.md", task_name):
                return ValidationResult(False, "DESIGN.md not found")
            return ValidationResult(True, "Design stage validated")

        # DEV stage - just check Claude completed
        if stage_upper == "DEV":
            return ValidationResult(True, "DEV stage completed - QA will validate")

        # TEST stage - check for TEST_PLAN.md
        if stage_upper == "TEST":
            if not artifact_exists("TEST_PLAN.md", task_name):
                return ValidationResult(False, "TEST_PLAN.md not found")
            return ValidationResult(True, "Test stage validated")

        # QA stage - check for QA_REPORT.md
        if stage_upper == "QA":
            if not artifact_exists("QA_REPORT.md", task_name):
                return ValidationResult(False, "QA_REPORT.md not found")
            report = read_artifact("QA_REPORT.md", task_name) or ""
            if "PASS" in report.upper() and "FAIL" not in report.upper():
                return ValidationResult(True, "QA passed")
            return ValidationResult(False, "QA failed", rollback_to="DEV")

        # SECURITY stage - check for SECURITY_CHECKLIST.md with APPROVED
        if stage_upper == "SECURITY":
            if artifact_exists("SECURITY_SKIP.md", task_name):
                return ValidationResult(True, "Security skipped")
            if not artifact_exists("SECURITY_CHECKLIST.md", task_name):
                return ValidationResult(False, "SECURITY_CHECKLIST.md not found")
            checklist = read_artifact("SECURITY_CHECKLIST.md", task_name) or ""
            if "APPROVED" in checklist.upper():
                return ValidationResult(True, "Security review approved")
            if "REJECTED" in checklist.upper() or "BLOCKED" in checklist.upper():
                return ValidationResult(
                    False, "Security review found blocking issues", rollback_to="DEV"
                )
            # Checklist exists but no clear marker - pass with warning
            return ValidationResult(True, "Security checklist created")

        # REVIEW stage - check for REVIEW_NOTES.md with APPROVE
        if stage_upper == "REVIEW":
            if not artifact_exists("REVIEW_NOTES.md", task_name):
                return ValidationResult(False, "REVIEW_NOTES.md not found")
            notes = read_artifact("REVIEW_NOTES.md", task_name) or ""
            if "APPROVE" in notes.upper():
                return ValidationResult(True, "Review approved")
            if "REQUEST_CHANGES" in notes.upper():
                return ValidationResult(
                    False, "Review requested changes", rollback_to="DEV"
                )
            return ValidationResult(False, "Review result unclear")

        # DOCS stage - check for DOCS_REPORT.md
        if stage_upper == "DOCS":
            if not artifact_exists("DOCS_REPORT.md", task_name):
                return ValidationResult(False, "DOCS_REPORT.md not found")
            return ValidationResult(True, "Docs stage validated")

        # Default: pass
        return ValidationResult(True, f"{stage} completed")
