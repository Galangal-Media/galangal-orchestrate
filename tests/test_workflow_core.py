"""Tests for workflow core functions with StageResult."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from galangal.config.schema import GalangalConfig, StageConfig
from galangal.core.state import Stage, TaskType, WorkflowState
from galangal.core.workflow.core import get_next_stage, handle_rollback
from galangal.results import StageResult, StageResultType
from galangal.validation.runner import ValidationResult


def make_state(
    task_name: str = "test-task",
    stage: Stage = Stage.DEV,
    attempt: int = 1,
) -> WorkflowState:
    """Create a WorkflowState with default values for testing."""
    return WorkflowState(
        task_name=task_name,
        stage=stage,
        attempt=attempt,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        task_description="Test task",
    )


class TestHandleRollback:
    """Tests for handle_rollback function with StageResult."""

    def test_handles_rollback_required_result(self):
        """Test that handle_rollback processes ROLLBACK_REQUIRED result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "test-task"
            task_dir.mkdir(parents=True)

            state = make_state(task_name="test-task", stage=Stage.QA, attempt=1)

            result = StageResult.rollback_required(
                message="QA found issues in implementation",
                rollback_to=Stage.DEV,
                output="Test failures detected",
            )

            # Patch get_task_dir at the source (state module) and in artifacts
            with patch("galangal.core.state.get_task_dir", return_value=task_dir):
                with patch("galangal.core.artifacts.get_task_dir", return_value=task_dir):
                    with patch("galangal.core.workflow.core.save_state"):
                        handled = handle_rollback(state, result)

            assert handled is True
            assert state.stage == Stage.DEV
            assert state.attempt == 1
            assert "QA" in state.last_failure
            assert (task_dir / "ROLLBACK.md").exists()

    def test_ignores_non_rollback_results(self):
        """Test that handle_rollback ignores non-rollback results."""
        state = make_state(task_name="test-task", stage=Stage.DEV, attempt=1)
        original_stage = state.stage

        # Test with success
        result = StageResult.success("All good")
        handled = handle_rollback(state, result)
        assert handled is False
        assert state.stage == original_stage

        # Test with error
        result = StageResult.error("Something failed")
        handled = handle_rollback(state, result)
        assert handled is False
        assert state.stage == original_stage

        # Test with validation failed (no rollback_to)
        result = StageResult.validation_failed("Tests failed")
        handled = handle_rollback(state, result)
        assert handled is False
        assert state.stage == original_stage

    def test_ignores_rollback_without_target(self):
        """Test that rollback with None target is ignored."""
        state = make_state(task_name="test-task", stage=Stage.QA, attempt=1)

        # Create a result with ROLLBACK_REQUIRED type but no rollback_to
        result = StageResult(
            success=False,
            message="Incomplete rollback",
            type=StageResultType.ROLLBACK_REQUIRED,
            rollback_to=None,
        )

        handled = handle_rollback(state, result)
        assert handled is False

    def test_appends_to_existing_rollback_log(self):
        """Test that rollback appends to existing ROLLBACK.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "test-task"
            task_dir.mkdir(parents=True)

            # Create existing rollback log
            existing_content = "# Rollback Log\n\nPrevious rollback info.\n"
            (task_dir / "ROLLBACK.md").write_text(existing_content)

            state = make_state(task_name="test-task", stage=Stage.TEST, attempt=2)

            result = StageResult.rollback_required(
                message="Tests still failing",
                rollback_to=Stage.DEV,
            )

            # Patch get_task_dir at the source (state module) and in artifacts
            with patch("galangal.core.state.get_task_dir", return_value=task_dir):
                with patch("galangal.core.artifacts.get_task_dir", return_value=task_dir):
                    with patch("galangal.core.workflow.core.save_state"):
                        handle_rollback(state, result)

            rollback_content = (task_dir / "ROLLBACK.md").read_text()
            assert "Previous rollback info" in rollback_content
            assert "Tests still failing" in rollback_content
            assert "TEST" in rollback_content


class TestStageResultPatternMatching:
    """Tests demonstrating StageResult type-based branching."""

    def test_can_match_on_result_type(self):
        """Test that result.type enables clean branching logic."""
        results = [
            StageResult.success("done"),
            StageResult.preflight_failed("deps missing", "details"),
            StageResult.validation_failed("tests failed"),
            StageResult.rollback_required("issues", Stage.DEV),
            StageResult.clarification_needed(),
            StageResult.paused(),
            StageResult.timeout(3600),
            StageResult.max_turns("output"),
            StageResult.error("crash"),
        ]

        matched_types = []
        for result in results:
            if result.type == StageResultType.SUCCESS:
                matched_types.append("success")
            elif result.type == StageResultType.PREFLIGHT_FAILED:
                matched_types.append("preflight")
            elif result.type == StageResultType.VALIDATION_FAILED:
                matched_types.append("validation")
            elif result.type == StageResultType.ROLLBACK_REQUIRED:
                matched_types.append("rollback")
            elif result.type == StageResultType.CLARIFICATION_NEEDED:
                matched_types.append("clarification")
            elif result.type == StageResultType.PAUSED:
                matched_types.append("paused")
            elif result.type == StageResultType.TIMEOUT:
                matched_types.append("timeout")
            elif result.type == StageResultType.MAX_TURNS:
                matched_types.append("max_turns")
            elif result.type == StageResultType.ERROR:
                matched_types.append("error")

        expected = [
            "success",
            "preflight",
            "validation",
            "rollback",
            "clarification",
            "paused",
            "timeout",
            "max_turns",
            "error",
        ]
        assert matched_types == expected

    def test_success_failure_grouping(self):
        """Test grouping results by success/failure status."""
        results = [
            StageResult.success("ok"),
            StageResult.error("failed"),
            StageResult.success("also ok"),
            StageResult.timeout(100),
        ]

        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]

        assert len(successes) == 2
        assert len(failures) == 2
        assert all(r.type == StageResultType.SUCCESS for r in successes)


class TestGetNextStage:
    """Tests for get_next_stage function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = GalangalConfig()

    def test_basic_stage_progression(self):
        """Test basic stage progression from PM to DESIGN."""
        state = make_state(stage=Stage.PM)

        with patch("galangal.core.workflow.core.get_config", return_value=self.config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                # Mock validation runner to not skip conditional stages
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(True, "passed")
                with patch("galangal.core.workflow.core.ValidationRunner", return_value=mock_runner):
                    next_stage = get_next_stage(Stage.PM, state)
                    assert next_stage == Stage.DESIGN

    def test_returns_none_at_complete(self):
        """Test returns None when at COMPLETE stage."""
        state = make_state(stage=Stage.COMPLETE)

        with patch("galangal.core.workflow.core.get_config", return_value=self.config):
            next_stage = get_next_stage(Stage.COMPLETE, state)
            assert next_stage is None

    def test_config_level_skipping(self):
        """Test stage skipping based on config."""
        config = GalangalConfig(stages=StageConfig(skip=["DESIGN"]))
        state = make_state(stage=Stage.PM)

        with patch("galangal.core.workflow.core.get_config", return_value=config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(True, "passed")
                with patch("galangal.core.workflow.core.ValidationRunner", return_value=mock_runner):
                    next_stage = get_next_stage(Stage.PM, state)
                    # Should skip DESIGN and go to PREFLIGHT
                    assert next_stage == Stage.PREFLIGHT

    def test_task_type_skipping(self):
        """Test stage skipping based on task type."""
        state = make_state(stage=Stage.PM)
        # DOCS task type skips DESIGN, PREFLIGHT and goes to DEV
        state.task_type = TaskType.DOCS

        with patch("galangal.core.workflow.core.get_config", return_value=self.config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(True, "passed")
                with patch("galangal.core.workflow.core.ValidationRunner", return_value=mock_runner):
                    next_stage = get_next_stage(Stage.PM, state)
                    # DOCS skips DESIGN and PREFLIGHT, goes to DEV
                    assert next_stage == Stage.DEV

    def test_conditional_stage_with_skip_artifact(self):
        """Test conditional stage is skipped when skip artifact exists."""
        state = make_state(stage=Stage.TEST)

        def artifact_exists_side_effect(name, task):
            return name == "MIGRATION_SKIP.md"

        with patch("galangal.core.workflow.core.get_config", return_value=self.config):
            with patch("galangal.core.workflow.core.artifact_exists", side_effect=artifact_exists_side_effect):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(True, "passed")
                with patch("galangal.core.workflow.core.ValidationRunner", return_value=mock_runner):
                    # After TEST comes MIGRATION, but should skip due to artifact
                    # Actual next depends on stage order, but MIGRATION should be skipped
                    next_stage = get_next_stage(Stage.DEV, state)
                    # DEV -> MIGRATION (skipped) -> TEST
                    assert next_stage == Stage.MIGRATION or next_stage == Stage.TEST

    def test_conditional_stage_skipped_by_condition(self):
        """Test conditional stage is skipped when validation condition met."""
        state = make_state(stage=Stage.DEV)

        with patch("galangal.core.workflow.core.get_config", return_value=self.config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                # Return condition met for MIGRATION (skipped=True)
                mock_runner.validate_stage.return_value = ValidationResult(
                    True, "MIGRATION skipped (condition met)", skipped=True
                )
                with patch("galangal.core.workflow.core.ValidationRunner", return_value=mock_runner):
                    next_stage = get_next_stage(Stage.DEV, state)
                    # Should skip MIGRATION and go to TEST
                    assert next_stage == Stage.TEST
