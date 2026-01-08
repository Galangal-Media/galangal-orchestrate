"""Tests for structured result types."""


from galangal.core.state import Stage
from galangal.results import Result, StageResult, StageResultType


class TestResult:
    """Tests for the base Result class."""

    def test_success_result_is_truthy(self):
        """Test that successful result is truthy."""
        result = Result(success=True, message="ok")
        assert result
        assert bool(result) is True

    def test_failure_result_is_falsy(self):
        """Test that failed result is falsy."""
        result = Result(success=False, message="failed")
        assert not result
        assert bool(result) is False

    def test_result_message_accessible(self):
        """Test that message is accessible."""
        result = Result(success=True, message="test message")
        assert result.message == "test message"


class TestStageResult:
    """Tests for the StageResult class."""

    def test_success_factory(self):
        """Test StageResult.success() factory method."""
        result = StageResult.success("Stage completed", output="some output")

        assert result.success is True
        assert result.type == StageResultType.SUCCESS
        assert result.message == "Stage completed"
        assert result.output == "some output"
        assert result.rollback_to is None

    def test_success_default_message(self):
        """Test StageResult.success() with default empty message."""
        result = StageResult.success()

        assert result.success is True
        assert result.message == ""

    def test_preflight_failed_factory(self):
        """Test StageResult.preflight_failed() factory method."""
        result = StageResult.preflight_failed(
            message="Missing dependencies", details="pip install failed"
        )

        assert result.success is False
        assert result.type == StageResultType.PREFLIGHT_FAILED
        assert result.message == "Missing dependencies"
        assert result.output == "pip install failed"

    def test_validation_failed_factory(self):
        """Test StageResult.validation_failed() factory method."""
        result = StageResult.validation_failed("Tests failed")

        assert result.success is False
        assert result.type == StageResultType.VALIDATION_FAILED
        assert result.message == "Tests failed"

    def test_rollback_required_factory(self):
        """Test StageResult.rollback_required() factory method."""
        result = StageResult.rollback_required(
            message="Need to fix design",
            rollback_to=Stage.DEV,
            output="Validation output",
        )

        assert result.success is False
        assert result.type == StageResultType.ROLLBACK_REQUIRED
        assert result.message == "Need to fix design"
        assert result.rollback_to == Stage.DEV
        assert result.output == "Validation output"

    def test_clarification_needed_factory(self):
        """Test StageResult.clarification_needed() factory method."""
        result = StageResult.clarification_needed()

        assert result.success is False
        assert result.type == StageResultType.CLARIFICATION_NEEDED
        assert "ANSWERS.md" in result.message

    def test_clarification_needed_custom_message(self):
        """Test StageResult.clarification_needed() with custom message."""
        result = StageResult.clarification_needed("Need more info")

        assert result.message == "Need more info"

    def test_paused_factory(self):
        """Test StageResult.paused() factory method."""
        result = StageResult.paused()

        assert result.success is False
        assert result.type == StageResultType.PAUSED
        assert "pause" in result.message.lower()

    def test_paused_custom_message(self):
        """Test StageResult.paused() with custom message."""
        result = StageResult.paused("Paused for review")

        assert result.message == "Paused for review"

    def test_timeout_factory(self):
        """Test StageResult.timeout() factory method."""
        result = StageResult.timeout(3600)

        assert result.success is False
        assert result.type == StageResultType.TIMEOUT
        assert "3600" in result.message

    def test_max_turns_factory(self):
        """Test StageResult.max_turns() factory method."""
        result = StageResult.max_turns(output="last output")

        assert result.success is False
        assert result.type == StageResultType.MAX_TURNS
        assert "Max turns" in result.message
        assert result.output == "last output"

    def test_error_factory(self):
        """Test StageResult.error() factory method."""
        result = StageResult.error("Claude crashed", output="stack trace")

        assert result.success is False
        assert result.type == StageResultType.ERROR
        assert result.message == "Claude crashed"
        assert result.output == "stack trace"

    def test_stage_result_inherits_bool_behavior(self):
        """Test that StageResult inherits __bool__ from Result."""
        success = StageResult.success("done")
        failure = StageResult.error("failed")

        assert success
        assert not failure


class TestStageResultType:
    """Tests for the StageResultType enum."""

    def test_all_expected_types_exist(self):
        """Test that all expected result types are defined."""
        expected_types = [
            "SUCCESS",
            "PREFLIGHT_FAILED",
            "VALIDATION_FAILED",
            "ROLLBACK_REQUIRED",
            "CLARIFICATION_NEEDED",
            "PAUSED",
            "TIMEOUT",
            "MAX_TURNS",
            "ERROR",
        ]

        for type_name in expected_types:
            assert hasattr(StageResultType, type_name)

    def test_types_are_distinct(self):
        """Test that all types have unique values."""
        values = [t.value for t in StageResultType]
        assert len(values) == len(set(values))
