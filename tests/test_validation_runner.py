"""Tests for validation runner."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from galangal.config.schema import (
    GalangalConfig,
    PreflightCheck,
    SkipCondition,
    StageValidation,
    ValidationCommand,
)
from galangal.validation.runner import ValidationResult, ValidationRunner


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = ValidationResult(success=True, message="All good")
        assert result.success is True
        assert result.message == "All good"
        assert result.output is None
        assert result.rollback_to is None

    def test_failure_with_rollback(self):
        """Test creating a failure result with rollback target."""
        result = ValidationResult(
            success=False,
            message="Tests failed",
            output="Error details",
            rollback_to="DEV",
        )
        assert result.success is False
        assert result.message == "Tests failed"
        assert result.output == "Error details"
        assert result.rollback_to == "DEV"


class TestValidationRunnerDefaults:
    """Tests for _validate_with_defaults method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_pm_stage_requires_spec_and_plan(self):
        """Test PM stage requires SPEC.md and PLAN.md."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                # Missing both artifacts
                with patch("galangal.validation.runner.artifact_exists", return_value=False):
                    result = runner._validate_with_defaults("PM", "test-task")
                    assert result.success is False
                    assert "SPEC.md" in result.message

                # Has SPEC.md but missing PLAN.md
                def exists_side_effect(name, task):
                    return name == "SPEC.md"

                with patch("galangal.validation.runner.artifact_exists", side_effect=exists_side_effect):
                    result = runner._validate_with_defaults("PM", "test-task")
                    assert result.success is False
                    assert "PLAN.md" in result.message

                # Has both artifacts
                with patch("galangal.validation.runner.artifact_exists", return_value=True):
                    result = runner._validate_with_defaults("PM", "test-task")
                    assert result.success is True

    def test_design_stage_can_be_skipped(self):
        """Test DESIGN stage checks for skip marker."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_side_effect(name, task):
                    return name == "DESIGN_SKIP.md"

                with patch("galangal.validation.runner.artifact_exists", side_effect=exists_side_effect):
                    result = runner._validate_with_defaults("DESIGN", "test-task")
                    assert result.success is True
                    assert "skipped" in result.message.lower()

    def test_dev_stage_always_passes(self):
        """Test DEV stage always passes (QA validates later)."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()
                result = runner._validate_with_defaults("DEV", "test-task")
                assert result.success is True

    def test_qa_stage_checks_report_content(self):
        """Test QA stage checks QA_REPORT.md content."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                # Missing report
                with patch("galangal.validation.runner.artifact_exists", return_value=False):
                    result = runner._validate_with_defaults("QA", "test-task")
                    assert result.success is False

                # Report with PASS
                with patch("galangal.validation.runner.artifact_exists", return_value=True):
                    with patch("galangal.validation.runner.read_artifact", return_value="Status: PASS"):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.success is True

                # Report with FAIL
                with patch("galangal.validation.runner.artifact_exists", return_value=True):
                    with patch("galangal.validation.runner.read_artifact", return_value="Status: FAIL"):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"

    def test_security_stage_checks_approval(self):
        """Test SECURITY stage checks for APPROVED marker."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_checklist_only(name, task):
                    return name == "SECURITY_CHECKLIST.md"

                # Checklist with APPROVED
                with patch("galangal.validation.runner.artifact_exists", side_effect=exists_checklist_only):
                    with patch("galangal.validation.runner.read_artifact", return_value="## Status: APPROVED"):
                        result = runner._validate_with_defaults("SECURITY", "test-task")
                        assert result.success is True

                # Checklist with REJECTED
                with patch("galangal.validation.runner.artifact_exists", side_effect=exists_checklist_only):
                    with patch("galangal.validation.runner.read_artifact", return_value="## Status: REJECTED"):
                        result = runner._validate_with_defaults("SECURITY", "test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"


class TestValidationRunnerQAReport:
    """Tests for _check_qa_report method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_qa_report_with_status_pass(self):
        """Test QA report with **Status:** PASS pattern."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                with patch("galangal.validation.runner.artifact_exists", return_value=True):
                    with patch("galangal.validation.runner.read_artifact", return_value="**Status:** PASS"):
                        result = runner._check_qa_report("test-task")
                        assert result.success is True

    def test_qa_report_with_status_fail(self):
        """Test QA report with **Status:** FAIL pattern."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                with patch("galangal.validation.runner.artifact_exists", return_value=True):
                    with patch("galangal.validation.runner.read_artifact", return_value="**Status:** FAIL"):
                        result = runner._check_qa_report("test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"

    def test_qa_report_missing(self):
        """Test missing QA report."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                with patch("galangal.validation.runner.artifact_exists", return_value=False):
                    result = runner._check_qa_report("test-task")
                    assert result.success is False
                    assert result.rollback_to == "DEV"

    def test_qa_report_unclear_status(self):
        """Test QA report with no clear status."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                with patch("galangal.validation.runner.artifact_exists", return_value=True):
                    with patch("galangal.validation.runner.read_artifact", return_value="Some content without status"):
                        result = runner._check_qa_report("test-task")
                        assert result.success is False
                        assert "No clear status" in result.message


class TestValidationRunnerArtifactMarkers:
    """Tests for _check_artifact_markers method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_artifact_with_pass_marker(self):
        """Test artifact containing pass marker."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                stage_config = StageValidation(
                    artifact="REVIEW_NOTES.md",
                    pass_marker="APPROVED",
                    fail_marker="REJECTED",
                )

                with patch("galangal.validation.runner.read_artifact", return_value="Decision: APPROVED"):
                    result = runner._check_artifact_markers(stage_config, "test-task")
                    assert result.success is True

    def test_artifact_with_fail_marker(self):
        """Test artifact containing fail marker."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                stage_config = StageValidation(
                    artifact="REVIEW_NOTES.md",
                    pass_marker="APPROVED",
                    fail_marker="REJECTED",
                )

                with patch("galangal.validation.runner.read_artifact", return_value="Decision: REJECTED"):
                    result = runner._check_artifact_markers(stage_config, "test-task")
                    assert result.success is False
                    assert result.rollback_to == "DEV"

    def test_artifact_missing(self):
        """Test missing artifact."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                stage_config = StageValidation(
                    artifact="REVIEW_NOTES.md",
                    pass_marker="APPROVED",
                )

                with patch("galangal.validation.runner.read_artifact", return_value=None):
                    result = runner._check_artifact_markers(stage_config, "test-task")
                    assert result.success is False


class TestValidationRunnerCommands:
    """Tests for _run_command method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_command_success(self):
        """Test successful command execution."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                cmd_config = ValidationCommand(name="test", command="echo hello")

                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "hello"

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    result = runner._run_command(cmd_config, "test-task", 300)
                    assert result.success is True
                    assert "passed" in result.message

    def test_command_failure(self):
        """Test failed command execution."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                cmd_config = ValidationCommand(name="test", command="exit 1")

                mock_result = MagicMock()
                mock_result.returncode = 1
                mock_result.stdout = ""
                mock_result.stderr = "error"

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    result = runner._run_command(cmd_config, "test-task", 300)
                    assert result.success is False
                    assert result.rollback_to == "DEV"

    def test_command_timeout(self):
        """Test command timeout."""
        import subprocess

        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                cmd_config = ValidationCommand(name="test", command="sleep 100")

                with patch(
                    "galangal.validation.runner.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("cmd", 30),
                ):
                    result = runner._run_command(cmd_config, "test-task", 30)
                    assert result.success is False
                    assert "timed out" in result.message


class TestValidationRunnerSkipConditions:
    """Tests for _should_skip method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_skip_when_no_files_match(self):
        """Test skip condition when no files match glob pattern."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                skip_condition = SkipCondition(no_files_match="*.sql")

                mock_result = MagicMock()
                mock_result.stdout = "src/main.py\nsrc/utils.py"

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    should_skip = runner._should_skip(skip_condition, "test-task")
                    assert should_skip is True  # No .sql files, should skip

    def test_no_skip_when_files_match(self):
        """Test no skip when files match glob pattern."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                skip_condition = SkipCondition(no_files_match="*.py")

                mock_result = MagicMock()
                mock_result.stdout = "src/main.py\nsrc/utils.py"

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    should_skip = runner._should_skip(skip_condition, "test-task")
                    assert should_skip is False  # .py files found, don't skip

    def test_skip_with_multiple_patterns(self):
        """Test skip condition with list of patterns."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                skip_condition = SkipCondition(no_files_match=["*.sql", "migrations/*"])

                mock_result = MagicMock()
                mock_result.stdout = "src/main.py"

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    should_skip = runner._should_skip(skip_condition, "test-task")
                    assert should_skip is True


class TestValidationRunnerPreflightChecks:
    """Tests for _run_preflight_checks method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_path_exists_check_pass(self):
        """Test path exists check when path exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").touch()

            with patch("galangal.validation.runner.get_config", return_value=self.config):
                with patch("galangal.validation.runner.get_project_root", return_value=project_root):
                    runner = ValidationRunner()

                    checks = [PreflightCheck(name="pyproject", path_exists="pyproject.toml")]

                    with patch("galangal.validation.runner.write_artifact"):
                        result = runner._run_preflight_checks(checks, "test-task")
                        assert result.success is True

    def test_path_exists_check_fail(self):
        """Test path exists check when path missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            with patch("galangal.validation.runner.get_config", return_value=self.config):
                with patch("galangal.validation.runner.get_project_root", return_value=project_root):
                    runner = ValidationRunner()

                    checks = [PreflightCheck(name="pyproject", path_exists="pyproject.toml")]

                    with patch("galangal.validation.runner.write_artifact"):
                        result = runner._run_preflight_checks(checks, "test-task")
                        assert result.success is False

    def test_command_check_pass(self):
        """Test command check when command succeeds."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                checks = [PreflightCheck(name="python", command="python --version")]

                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "Python 3.12.0"

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    with patch("galangal.validation.runner.write_artifact"):
                        result = runner._run_preflight_checks(checks, "test-task")
                        assert result.success is True

    def test_warn_only_check_doesnt_fail(self):
        """Test warn_only check doesn't cause failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            with patch("galangal.validation.runner.get_config", return_value=self.config):
                with patch("galangal.validation.runner.get_project_root", return_value=project_root):
                    runner = ValidationRunner()

                    checks = [
                        PreflightCheck(name="optional", path_exists="optional.txt", warn_only=True)
                    ]

                    with patch("galangal.validation.runner.write_artifact"):
                        result = runner._run_preflight_checks(checks, "test-task")
                        assert result.success is True  # warn_only doesn't fail
