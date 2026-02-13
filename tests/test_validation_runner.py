"""Tests for validation runner."""

import tempfile
import textwrap
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

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_side_effect
                ):
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

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_side_effect
                ):
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
        """Test QA stage checks QA_DECISION file first, then QA_REPORT.md."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                # Missing report and decision file
                with patch("galangal.validation.runner.artifact_exists", return_value=False):
                    result = runner._validate_with_defaults("QA", "test-task")
                    assert result.success is False
                    assert result.rollback_to == "DEV"

                # Decision file with PASS
                def exists_decision(name, task):
                    return name == "QA_DECISION"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="PASS"):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.success is True

                # Decision file with FAIL
                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="FAIL"):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"

                # Report exists but no decision file - needs user decision
                def exists_report_only(name, task):
                    return name == "QA_REPORT.md"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_report_only
                ):
                    with patch(
                        "galangal.validation.runner.read_artifact", return_value="Status: PASS"
                    ):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.needs_user_decision is True

    def test_security_stage_checks_approval(self):
        """Test SECURITY stage checks SECURITY_DECISION file first."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                # Decision file with APPROVED
                def exists_decision(name, task):
                    return name == "SECURITY_DECISION"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="APPROVED"):
                        result = runner._validate_with_defaults("SECURITY", "test-task")
                        assert result.success is True

                # Decision file with REJECTED
                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="REJECTED"):
                        result = runner._validate_with_defaults("SECURITY", "test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"

                # Decision file with BLOCKED
                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="BLOCKED"):
                        result = runner._validate_with_defaults("SECURITY", "test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"

                # Checklist exists but no decision file - needs user decision
                def exists_checklist_only(name, task):
                    return name == "SECURITY_CHECKLIST.md"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_checklist_only
                ):
                    with patch(
                        "galangal.validation.runner.read_artifact",
                        return_value="## Security Review\nReview done.",
                    ):
                        result = runner._validate_with_defaults("SECURITY", "test-task")
                        assert result.needs_user_decision is True

                # Neither checklist nor decision file - should fail
                with patch("galangal.validation.runner.artifact_exists", return_value=False):
                    result = runner._validate_with_defaults("SECURITY", "test-task")
                    assert result.success is False
                    assert result.rollback_to == "DEV"

                # Security skip marker exists - should pass
                def exists_skip(name, task):
                    return name == "SECURITY_SKIP.md"

                with patch("galangal.validation.runner.artifact_exists", side_effect=exists_skip):
                    result = runner._validate_with_defaults("SECURITY", "test-task")
                    assert result.success is True


class TestValidationRunnerQAReport:
    """Tests for QA validation via _validate_with_defaults (metadata-driven)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_qa_decision_pass(self):
        """Test QA_DECISION file with PASS via _validate_with_defaults."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_decision(name, task):
                    return name == "QA_DECISION"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="PASS"):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.success is True

    def test_qa_decision_fail(self):
        """Test QA_DECISION file with FAIL via _validate_with_defaults."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_decision(name, task):
                    return name == "QA_DECISION"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="FAIL"):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.success is False
                        assert result.rollback_to == "DEV"

    def test_qa_report_exists_no_decision(self):
        """Test QA_REPORT.md exists but no QA_DECISION - needs user decision."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_report_only(name, task):
                    return name == "QA_REPORT.md"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_report_only
                ):
                    with patch(
                        "galangal.validation.runner.read_artifact", return_value="QA Report content"
                    ):
                        result = runner._validate_with_defaults("QA", "test-task")
                        assert result.needs_user_decision is True

    def test_qa_report_and_decision_missing(self):
        """Test both QA_REPORT.md and QA_DECISION missing."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                with patch("galangal.validation.runner.artifact_exists", return_value=False):
                    result = runner._validate_with_defaults("QA", "test-task")
                    assert result.success is False
                    assert result.rollback_to == "DEV"


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

                with patch(
                    "galangal.validation.runner.read_artifact", return_value="Decision: APPROVED"
                ):
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

                with patch(
                    "galangal.validation.runner.read_artifact", return_value="Decision: REJECTED"
                ):
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
                mock_result.returncode = 0

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
                mock_result.returncode = 0

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
                mock_result.returncode = 0

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    should_skip = runner._should_skip(skip_condition, "test-task")
                    assert should_skip is True

    def test_no_skip_when_git_fails(self):
        """Test no skip when git diff returns non-zero exit code."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                skip_condition = SkipCondition(no_files_match="*.sql")

                mock_result = MagicMock()
                mock_result.stdout = ""
                mock_result.returncode = 128  # Git error (e.g., branch not found)

                with patch("galangal.validation.runner.subprocess.run", return_value=mock_result):
                    should_skip = runner._should_skip(skip_condition, "test-task")
                    assert should_skip is False  # On git error, don't skip


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
                with patch(
                    "galangal.validation.runner.get_project_root", return_value=project_root
                ):
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
                with patch(
                    "galangal.validation.runner.get_project_root", return_value=project_root
                ):
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
                with patch(
                    "galangal.validation.runner.get_project_root", return_value=project_root
                ):
                    runner = ValidationRunner()

                    checks = [
                        PreflightCheck(name="optional", path_exists="optional.txt", warn_only=True)
                    ]

                    with patch("galangal.validation.runner.write_artifact"):
                        result = runner._run_preflight_checks(checks, "test-task")
                        assert result.success is True  # warn_only doesn't fail


class TestValidationRunnerMetadataDriven:
    """Tests for metadata-driven validation dispatch."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_unknown_stage_passes_gracefully(self):
        """Test that an unknown stage name passes gracefully."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()
                result = runner._validate_with_defaults("NONEXISTENT", "test-task")
                assert result.success is True
                assert "NONEXISTENT" in result.message

    def test_preflight_defaults_to_none(self):
        """Test PREFLIGHT with default_validation='none' always passes."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()
                result = runner._validate_with_defaults("PREFLIGHT", "test-task")
                assert result.success is True

    def test_complete_defaults_to_none(self):
        """Test COMPLETE with default_validation='none' always passes."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()
                result = runner._validate_with_defaults("COMPLETE", "test-task")
                assert result.success is True

    def test_review_decision_or_markers_with_decision(self):
        """Test REVIEW uses decision_or_markers and finds decision file."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_decision(name, task):
                    return name == "REVIEW_DECISION"

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_decision
                ):
                    with patch("galangal.validation.runner.read_artifact", return_value="APPROVE"):
                        result = runner._validate_with_defaults("REVIEW", "test-task")
                        assert result.success is True

    def test_review_decision_or_markers_falls_through(self):
        """Test REVIEW falls through to artifact check when no decision file."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = ValidationRunner()

                def exists_notes(name, task):
                    if name == "REVIEW_NOTES.md":
                        return True
                    if name == "REVIEW_DECISION":
                        return False
                    return False

                with patch(
                    "galangal.validation.runner.artifact_exists", side_effect=exists_notes
                ):
                    with patch(
                        "galangal.validation.runner.read_artifact",
                        return_value="Review notes content",
                    ):
                        # Decision file missing, report exists -> needs_user_decision
                        # from validate_stage_decision, but since it returns
                        # needs_user_decision (no rollback_to), it falls through
                        # to artifact check where REVIEW_NOTES.md exists -> pass
                        result = runner._validate_with_defaults("REVIEW", "test-task")
                        # The decision validation returns needs_user_decision=True
                        # with no rollback_to, so it falls through to artifact check
                        # But the fallback artifact check also needs
                        # produces_artifacts to pass. REVIEW_NOTES.md exists -> pass
                        assert result.success is True


class TestValidationRunnerJUnitXML:
    """Tests for JUnit XML parsing and integration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def _make_runner(self):
        """Create a ValidationRunner with mocked config."""
        return ValidationRunner()

    def test_parse_junit_xml_with_failures(self):
        """Test parsing valid JUnit XML with failures."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite name="pytest" tests="5" failures="2" errors="0" skipped="1" time="3.45">
                <testcase classname="tests.test_foo" name="test_ok" time="0.5"/>
                <testcase classname="tests.test_foo" name="test_also_ok" time="0.3"/>
                <testcase classname="tests.test_bar" name="test_fail1" time="1.0">
                    <failure message="assert 1 == 2">AssertionError: assert 1 == 2</failure>
                </testcase>
                <testcase classname="tests.test_bar" name="test_fail2" time="0.8">
                    <failure message="KeyError: 'missing'">KeyError: 'missing'</failure>
                </testcase>
                <testcase classname="tests.test_baz" name="test_skip" time="0.0">
                    <skipped message="skipped"/>
                </testcase>
            </testsuite>
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write(xml_content)
            xml_path = Path(f.name)

        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = self._make_runner()
                result = runner._parse_junit_xml(xml_path)

        assert "2 passed" in result["counts"]
        assert "2 failed" in result["counts"]
        assert "1 skipped" in result["counts"]
        assert result["duration"] == "3.45s"
        assert len(result["failed_tests"]) == 2
        assert "test_fail1" in result["failed_tests"][0]
        xml_path.unlink()

    def test_parse_junit_xml_multi_suite(self):
        """Test parsing JUnit XML with multiple testsuite elements."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites>
                <testsuite name="suite1" tests="3" failures="1" errors="0" skipped="0" time="1.0">
                    <testcase classname="s1" name="test_a" time="0.5"/>
                    <testcase classname="s1" name="test_b" time="0.3"/>
                    <testcase classname="s1" name="test_c" time="0.2">
                        <failure message="fail">fail</failure>
                    </testcase>
                </testsuite>
                <testsuite name="suite2" tests="2" failures="0" errors="1" skipped="0" time="2.0">
                    <testcase classname="s2" name="test_d" time="1.0"/>
                    <testcase classname="s2" name="test_e" time="1.0">
                        <error message="RuntimeError">RuntimeError</error>
                    </testcase>
                </testsuite>
            </testsuites>
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write(xml_content)
            xml_path = Path(f.name)

        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = self._make_runner()
                result = runner._parse_junit_xml(xml_path)

        # 5 total tests, 1 failure, 1 error, 0 skipped = 3 passed
        assert "3 passed" in result["counts"]
        assert "1 failed" in result["counts"]
        assert "1 errors" in result["counts"]
        assert result["duration"] == "3.00s"
        assert len(result["failed_tests"]) == 2
        xml_path.unlink()

    def test_parse_junit_xml_missing_file(self):
        """Test parsing returns empty result for missing file."""
        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = self._make_runner()
                result = runner._parse_junit_xml(Path("/nonexistent/junit.xml"))

        assert result["counts"] == ""
        assert result["failed_tests"] == []

    def test_parse_junit_xml_malformed(self):
        """Test parsing returns empty result for malformed XML."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("<not valid xml<<<")
            xml_path = Path(f.name)

        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = self._make_runner()
                result = runner._parse_junit_xml(xml_path)

        assert result["counts"] == ""
        assert result["failed_tests"] == []
        xml_path.unlink()

    def test_try_parse_junit_xml_explicit_config(self):
        """Test _try_parse_junit_xml with explicit config path."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite name="pytest" tests="3" failures="0" errors="0" skipped="0" time="1.0">
                <testcase classname="t" name="test_a" time="0.5"/>
                <testcase classname="t" name="test_b" time="0.3"/>
                <testcase classname="t" name="test_c" time="0.2"/>
            </testsuite>
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = Path(tmpdir) / "results.xml"
            xml_path.write_text(xml_content)

            cmd_config = ValidationCommand(
                name="test",
                command="pytest",
                junit_xml=str(xml_path),
            )

            with patch("galangal.validation.runner.get_config", return_value=self.config):
                with patch(
                    "galangal.validation.runner.get_project_root", return_value=Path(tmpdir)
                ):
                    runner = self._make_runner()
                    result = runner._try_parse_junit_xml("test-task", cmd_config)

            assert "3 passed" in result["counts"]

    def test_try_parse_junit_xml_convention_path(self):
        """Test _try_parse_junit_xml finds {task_dir}/junit.xml by convention."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0" time="0.5">
                <testcase classname="t" name="test_a" time="0.3"/>
                <testcase classname="t" name="test_b" time="0.2"/>
            </testsuite>
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "my-task"
            task_dir.mkdir(parents=True)
            (task_dir / "junit.xml").write_text(xml_content)

            with patch("galangal.validation.runner.get_config", return_value=self.config):
                with patch(
                    "galangal.validation.runner.get_project_root", return_value=Path(tmpdir)
                ):
                    runner = self._make_runner()
                    with patch(
                        "galangal.core.state.get_task_dir", return_value=task_dir
                    ):
                        result = runner._try_parse_junit_xml("my-task")

            assert "2 passed" in result["counts"]

    def test_write_test_summary_prefers_xml(self):
        """Test _write_test_summary uses XML when available, merges coverage from stdout."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite name="pytest" tests="4" failures="1" errors="0" skipped="0" time="2.0">
                <testcase classname="t" name="test_a" time="0.5"/>
                <testcase classname="t" name="test_b" time="0.5"/>
                <testcase classname="t" name="test_c" time="0.5"/>
                <testcase classname="t" name="test_fail" time="0.5">
                    <failure message="assert False">assert False</failure>
                </testcase>
            </testsuite>
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "test-task"
            task_dir.mkdir(parents=True)
            (task_dir / "junit.xml").write_text(xml_content)

            # Stdout has coverage info that XML doesn't
            stdout_output = "TOTAL                  100     10    90%\n"
            command_results = {
                "has_failure": True,
                "first_failure_message": "tests: failed",
                "aggregated_output": stdout_output,
                "results": [("pytest tests", False, stdout_output)],
                "command_configs": {
                    "pytest tests": ValidationCommand(name="pytest tests", command="pytest"),
                },
            }

            written_content = {}

            def capture_write(name, content, task):
                written_content[name] = content

            with patch("galangal.validation.runner.get_config", return_value=self.config):
                with patch(
                    "galangal.validation.runner.get_project_root", return_value=Path(tmpdir)
                ):
                    runner = self._make_runner()
                    with patch(
                        "galangal.core.state.get_task_dir", return_value=task_dir
                    ):
                        with patch(
                            "galangal.validation.runner.write_artifact",
                            side_effect=capture_write,
                        ):
                            runner._write_test_summary("test-task", command_results)

            summary = written_content.get("TEST_SUMMARY.md", "")
            assert "3 passed" in summary
            assert "1 failed" in summary
            assert "90%" in summary  # Coverage merged from stdout

    def test_write_test_summary_falls_back_to_stdout(self):
        """Test _write_test_summary falls back to stdout when no XML exists."""
        stdout_output = (
            "5 passed, 1 failed in 2.50s\n"
            "FAILED tests/test_foo.py::test_bar - AssertionError\n"
        )
        command_results = {
            "has_failure": True,
            "first_failure_message": "tests: failed",
            "aggregated_output": stdout_output,
            "results": [("pytest tests", False, stdout_output)],
            "command_configs": {
                "pytest tests": ValidationCommand(name="pytest tests", command="pytest"),
            },
        }

        written_content = {}

        def capture_write(name, content, task):
            written_content[name] = content

        with patch("galangal.validation.runner.get_config", return_value=self.config):
            with patch("galangal.validation.runner.get_project_root", return_value=Path("/tmp")):
                runner = self._make_runner()
                with patch(
                    "galangal.core.state.get_task_dir",
                    return_value=Path("/nonexistent/task"),
                ):
                    with patch(
                        "galangal.validation.runner.write_artifact",
                        side_effect=capture_write,
                    ):
                        runner._write_test_summary("test-task", command_results)

        summary = written_content.get("TEST_SUMMARY.md", "")
        assert "5 passed" in summary
        assert "test_foo.py::test_bar" in summary
