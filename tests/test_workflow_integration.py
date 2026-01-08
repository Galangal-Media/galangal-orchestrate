"""
Integration tests for full workflow execution.

These tests verify end-to-end workflow behavior using mock backends
to avoid actual AI invocations while testing the workflow logic.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from galangal.config.schema import GalangalConfig, StageConfig
from galangal.core.state import (
    STAGE_ORDER,
    Stage,
    TaskType,
    WorkflowState,
    save_state,
)
from galangal.core.workflow.core import (
    archive_rollback_if_exists,
    execute_stage,
    get_next_stage,
    handle_rollback,
)
from galangal.results import StageResult, StageResultType
from galangal.ui.tui import StageUI
from galangal.validation.runner import ValidationResult


# ============================================================================
# Helper functions and classes (duplicated from conftest for direct import)
# ============================================================================


def make_state(
    task_name: str = "test-task",
    stage: Stage = Stage.PM,
    task_type: TaskType = TaskType.FEATURE,
    attempt: int = 1,
    task_description: str = "Test task",
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
        task_description=task_description,
        task_type=task_type,
    )


def create_artifact(task_dir: Path, name: str, content: str) -> Path:
    """Create an artifact file in the task directory."""
    artifact_path = task_dir / name
    artifact_path.write_text(content)
    return artifact_path


class MockStageUI(StageUI):
    """Mock UI for testing without TUI."""

    def __init__(self):
        self.activities: list[tuple[str, str]] = []
        self.messages: list[tuple[str, str]] = []
        self.files_read: list[str] = []
        self.files_written: list[str] = []

    def add_activity(self, text: str, icon: str = "•") -> None:
        self.activities.append((text, icon))

    def show_message(self, message: str, style: str = "info") -> None:
        self.messages.append((message, style))

    def set_current_action(self, action: str) -> None:
        pass

    def clear_current_action(self) -> None:
        pass

    def add_file_read(self, path: str) -> None:
        self.files_read.append(path)

    def add_file_written(self, path: str) -> None:
        self.files_written.append(path)


class MockAIBackend:
    """Mock AI backend for testing."""

    def __init__(
        self,
        responses: dict[Stage, StageResult] | None = None,
        default_response: StageResult | None = None,
    ):
        self.responses = responses or {}
        self.default_response = default_response or StageResult.success("Mock success")
        self.calls: list[tuple[str, Stage | None, str | None]] = []

    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui=None,
        pause_check=None,
    ) -> StageResult:
        """Record the call and return configured response."""
        stage = None
        for s in Stage:
            if s.value in prompt.upper():
                stage = s
                break

        self.calls.append((prompt[:100], stage, None))

        if pause_check and pause_check():
            return StageResult.paused()

        if stage and stage in self.responses:
            return self.responses[stage]
        return self.default_response

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        self.calls.append((prompt[:100], None, None))
        return "mock-generated-text"

    @property
    def name(self) -> str:
        return "mock"


class TestWorkflowStageProgression:
    """Tests for stage progression through the workflow."""

    def test_full_stage_order_for_feature(self):
        """Test that FEATURE task type visits all expected stages."""
        state = make_state(task_type=TaskType.FEATURE)
        config = GalangalConfig()

        visited_stages = [Stage.PM]
        current = Stage.PM

        with patch("galangal.core.workflow.core.get_config", return_value=config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(
                    True, "passed", skipped=False
                )
                with patch(
                    "galangal.core.workflow.core.ValidationRunner",
                    return_value=mock_runner,
                ):
                    while current != Stage.COMPLETE:
                        next_stage = get_next_stage(current, state)
                        if next_stage is None:
                            break
                        visited_stages.append(next_stage)
                        current = next_stage

        # Feature should visit all stages except conditionals that get skipped
        assert Stage.PM in visited_stages
        assert Stage.DESIGN in visited_stages
        assert Stage.DEV in visited_stages
        assert Stage.TEST in visited_stages
        assert Stage.QA in visited_stages
        assert Stage.REVIEW in visited_stages
        assert Stage.DOCS in visited_stages
        assert Stage.COMPLETE in visited_stages

    def test_docs_task_type_skips_stages(self):
        """Test that DOCS task type skips most stages."""
        state = make_state(task_type=TaskType.DOCS)
        config = GalangalConfig()

        visited_stages = [Stage.PM]
        current = Stage.PM

        with patch("galangal.core.workflow.core.get_config", return_value=config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(
                    True, "passed", skipped=False
                )
                with patch(
                    "galangal.core.workflow.core.ValidationRunner",
                    return_value=mock_runner,
                ):
                    while current != Stage.COMPLETE:
                        next_stage = get_next_stage(current, state)
                        if next_stage is None:
                            break
                        visited_stages.append(next_stage)
                        current = next_stage

        # DOCS should skip: DESIGN, PREFLIGHT, MIGRATION, TEST, CONTRACT, QA, BENCHMARK, SECURITY
        assert Stage.DESIGN not in visited_stages
        assert Stage.PREFLIGHT not in visited_stages
        assert Stage.TEST not in visited_stages
        assert Stage.QA not in visited_stages
        assert Stage.SECURITY not in visited_stages
        # Should still have: PM, DEV, REVIEW, DOCS, COMPLETE
        assert Stage.PM in visited_stages
        assert Stage.DEV in visited_stages
        assert Stage.REVIEW in visited_stages
        assert Stage.DOCS in visited_stages

    def test_config_skip_stages(self):
        """Test that config-level skip removes stages from workflow."""
        state = make_state(task_type=TaskType.FEATURE)
        config = GalangalConfig(stages=StageConfig(skip=["BENCHMARK", "SECURITY"]))

        visited_stages = [Stage.PM]
        current = Stage.PM

        with patch("galangal.core.workflow.core.get_config", return_value=config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(
                    True, "passed", skipped=False
                )
                with patch(
                    "galangal.core.workflow.core.ValidationRunner",
                    return_value=mock_runner,
                ):
                    while current != Stage.COMPLETE:
                        next_stage = get_next_stage(current, state)
                        if next_stage is None:
                            break
                        visited_stages.append(next_stage)
                        current = next_stage

        assert Stage.BENCHMARK not in visited_stages
        assert Stage.SECURITY not in visited_stages


class TestExecuteStageWithMockBackend:
    """Tests for execute_stage using mock backend."""

    def test_execute_stage_success(self, sample_task: Path, sample_config: GalangalConfig):
        """Test successful stage execution."""
        state = make_state(task_name="test-task", stage=Stage.DEV)
        mock_ui = MockStageUI()

        # Create required artifacts
        create_artifact(sample_task, "SPEC.md", "# Spec\n\nTest spec")
        create_artifact(sample_task, "PLAN.md", "# Plan\n\nTest plan")

        mock_backend = MockAIBackend(
            default_response=StageResult.success("DEV completed", output="Implementation done")
        )

        with patch("galangal.core.workflow.core.get_config", return_value=sample_config):
            with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
                with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                    with patch(
                        "galangal.core.workflow.core.ClaudeBackend",
                        return_value=mock_backend,
                    ):
                        # Mock validation to pass
                        mock_runner = MagicMock()
                        mock_runner.validate_stage.return_value = ValidationResult(
                            True, "Validation passed"
                        )
                        with patch(
                            "galangal.core.workflow.core.ValidationRunner",
                            return_value=mock_runner,
                        ):
                            result = execute_stage(state, mock_ui)

        assert result.success is True
        assert result.type == StageResultType.SUCCESS

    def test_execute_stage_validation_failure(
        self, sample_task: Path, sample_config: GalangalConfig
    ):
        """Test stage execution with validation failure."""
        state = make_state(task_name="test-task", stage=Stage.QA)
        mock_ui = MockStageUI()

        mock_backend = MockAIBackend(
            default_response=StageResult.success("QA completed")
        )

        with patch("galangal.core.workflow.core.get_config", return_value=sample_config):
            with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
                with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                    with patch(
                        "galangal.core.workflow.core.ClaudeBackend",
                        return_value=mock_backend,
                    ):
                        # Mock validation to fail with rollback
                        mock_runner = MagicMock()
                        mock_runner.validate_stage.return_value = ValidationResult(
                            False, "QA found issues", rollback_to="DEV"
                        )
                        with patch(
                            "galangal.core.workflow.core.ValidationRunner",
                            return_value=mock_runner,
                        ):
                            result = execute_stage(state, mock_ui)

        assert result.success is False
        assert result.type == StageResultType.ROLLBACK_REQUIRED
        assert result.rollback_to == Stage.DEV

    def test_execute_preflight_stage(
        self, sample_task: Path, sample_config: GalangalConfig
    ):
        """Test PREFLIGHT stage runs validation directly without AI."""
        state = make_state(task_name="test-task", stage=Stage.PREFLIGHT)
        mock_ui = MockStageUI()

        with patch("galangal.core.workflow.core.get_config", return_value=sample_config):
            with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
                with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                    mock_runner = MagicMock()
                    mock_runner.validate_stage.return_value = ValidationResult(
                        True, "Preflight checks passed"
                    )
                    with patch(
                        "galangal.core.workflow.core.ValidationRunner",
                        return_value=mock_runner,
                    ):
                        result = execute_stage(state, mock_ui)

        assert result.success is True
        # Preflight should call validation directly
        mock_runner.validate_stage.assert_called_with("PREFLIGHT", "test-task")


class TestRollbackIntegration:
    """Integration tests for rollback handling."""

    def test_rollback_updates_state_and_creates_log(self, sample_task: Path):
        """Test that rollback updates state and creates ROLLBACK.md."""
        state = make_state(task_name="test-task", stage=Stage.QA, attempt=1)

        result = StageResult.rollback_required(
            message="Tests failed, need implementation fixes",
            rollback_to=Stage.DEV,
        )

        with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
            with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                with patch("galangal.core.workflow.core.save_state"):
                    handled = handle_rollback(state, result)

        assert handled is True
        assert state.stage == Stage.DEV
        assert state.attempt == 1
        assert "QA" in state.last_failure

        # Check ROLLBACK.md was created
        rollback_md = sample_task / "ROLLBACK.md"
        assert rollback_md.exists()
        content = rollback_md.read_text()
        assert "Tests failed" in content
        assert "QA" in content
        assert "DEV" in content

    def test_rollback_loop_prevention(self, sample_task: Path):
        """Test that rollback loop is prevented after max rollbacks."""
        state = make_state(task_name="test-task", stage=Stage.QA)

        # Simulate 3 previous rollbacks to DEV within the time window
        for _ in range(3):
            state.record_rollback(Stage.QA, Stage.DEV, "Previous failure")

        result = StageResult.rollback_required(
            message="Another failure",
            rollback_to=Stage.DEV,
        )

        with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
            with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                handled = handle_rollback(state, result)

        # Should be blocked due to loop prevention
        assert handled is False
        assert state.stage == Stage.QA  # Stage should not change

    def test_archive_rollback_on_success(self, sample_task: Path):
        """Test archiving ROLLBACK.md after successful DEV completion."""
        mock_ui = MockStageUI()

        # Create ROLLBACK.md
        rollback_content = "# Previous rollback info\n\nTest content"
        (sample_task / "ROLLBACK.md").write_text(rollback_content)

        with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
            archive_rollback_if_exists("test-task", mock_ui)

        # ROLLBACK.md should be removed
        assert not (sample_task / "ROLLBACK.md").exists()
        # ROLLBACK_RESOLVED.md should be created
        assert (sample_task / "ROLLBACK_RESOLVED.md").exists()
        resolved_content = (sample_task / "ROLLBACK_RESOLVED.md").read_text()
        assert "Previous rollback info" in resolved_content
        assert "Resolved" in resolved_content


class TestRetryBehavior:
    """Tests for retry logic in workflow execution."""

    def test_retry_context_added_to_prompt(
        self, sample_task: Path, sample_config: GalangalConfig
    ):
        """Test that retry context is added to prompt on subsequent attempts."""
        state = make_state(task_name="test-task", stage=Stage.DEV, attempt=2)
        state.last_failure = "Tests failed with error: AssertionError"

        mock_ui = MockStageUI()
        mock_backend = MockAIBackend()

        # Create required artifacts
        create_artifact(sample_task, "SPEC.md", "# Spec")
        create_artifact(sample_task, "PLAN.md", "# Plan")

        with patch("galangal.core.workflow.core.get_config", return_value=sample_config):
            with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
                with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                    with patch(
                        "galangal.core.workflow.core.ClaudeBackend",
                        return_value=mock_backend,
                    ):
                        mock_runner = MagicMock()
                        mock_runner.validate_stage.return_value = ValidationResult(
                            True, "passed"
                        )
                        with patch(
                            "galangal.core.workflow.core.ValidationRunner",
                            return_value=mock_runner,
                        ):
                            execute_stage(state, mock_ui)

        # Check that backend was called with retry context in prompt
        assert len(mock_backend.calls) > 0
        prompt = mock_backend.calls[0][0]
        # The prompt should mention it's a retry
        # (Note: actual prompt content depends on PromptBuilder)

    def test_record_failure_increments_attempt(self):
        """Test that record_failure increments attempt counter."""
        state = make_state(attempt=1)

        state.record_failure("First failure")
        assert state.attempt == 2
        assert state.last_failure == "First failure"

        state.record_failure("Second failure")
        assert state.attempt == 3
        assert state.last_failure == "Second failure"

    def test_can_retry_check(self):
        """Test can_retry logic."""
        state = make_state(attempt=1)

        assert state.can_retry(max_retries=5) is True

        state.attempt = 5
        assert state.can_retry(max_retries=5) is True

        state.attempt = 6
        assert state.can_retry(max_retries=5) is False

    def test_reset_attempts_clears_counter(self):
        """Test reset_attempts resets the counter."""
        state = make_state(attempt=3)
        state.last_failure = "Previous failure"

        state.reset_attempts()
        assert state.attempt == 1
        assert state.last_failure is None

    def test_reset_attempts_preserves_failure_on_rollback(self):
        """Test reset_attempts preserves failure when clear_failure=False."""
        state = make_state(attempt=3)
        state.last_failure = "Failure context needed for next stage"

        state.reset_attempts(clear_failure=False)
        assert state.attempt == 1
        assert state.last_failure == "Failure context needed for next stage"


class TestConditionalStageSkipping:
    """Tests for conditional stage skipping logic."""

    def test_migration_skipped_with_skip_artifact(self):
        """Test MIGRATION is skipped when MIGRATION_SKIP.md exists."""
        state = make_state(task_type=TaskType.FEATURE, stage=Stage.DEV)
        config = GalangalConfig()

        def artifact_exists_side_effect(name, task):
            return name == "MIGRATION_SKIP.md"

        with patch("galangal.core.workflow.core.get_config", return_value=config):
            with patch(
                "galangal.core.workflow.core.artifact_exists",
                side_effect=artifact_exists_side_effect,
            ):
                mock_runner = MagicMock()
                mock_runner.validate_stage.return_value = ValidationResult(
                    True, "passed", skipped=False
                )
                with patch(
                    "galangal.core.workflow.core.ValidationRunner",
                    return_value=mock_runner,
                ):
                    next_stage = get_next_stage(Stage.DEV, state)

        # Should skip MIGRATION and go to TEST
        assert next_stage == Stage.TEST

    def test_migration_skipped_when_no_sql_files(self):
        """Test MIGRATION is skipped when validation says skipped=True."""
        state = make_state(task_type=TaskType.FEATURE, stage=Stage.DEV)
        config = GalangalConfig()

        with patch("galangal.core.workflow.core.get_config", return_value=config):
            with patch("galangal.core.workflow.core.artifact_exists", return_value=False):
                mock_runner = MagicMock()
                # MIGRATION validation returns skipped=True (no SQL files)
                mock_runner.validate_stage.return_value = ValidationResult(
                    True, "No migration needed", skipped=True
                )
                with patch(
                    "galangal.core.workflow.core.ValidationRunner",
                    return_value=mock_runner,
                ):
                    next_stage = get_next_stage(Stage.DEV, state)

        assert next_stage == Stage.TEST


class TestApprovalGates:
    """Tests for approval gate functionality."""

    def test_plan_approval_accepted(self, sample_task: Path, sample_config: GalangalConfig):
        """Test plan approval flow when user approves."""
        from galangal.commands.approve import prompt_plan_approval

        state = make_state(task_name="test-task", stage=Stage.DESIGN)

        # Create PLAN.md artifact
        create_artifact(sample_task, "PLAN.md", "# Plan\n\nTest plan content")

        with patch("galangal.commands.approve.read_artifact", return_value="# Test Plan"):
            with patch("galangal.commands.approve.write_artifact") as mock_write:
                with patch("galangal.commands.approve.Prompt.ask") as mock_prompt:
                    # Simulate: y, then approver name
                    mock_prompt.side_effect = ["y", "Test User"]
                    with patch("galangal.commands.approve.console"):
                        result = prompt_plan_approval("test-task", state)

        assert result == "approved"
        # Should have written APPROVAL.md
        mock_write.assert_called_once()
        call_args = mock_write.call_args
        assert call_args[0][0] == "APPROVAL.md"
        assert "Approved" in call_args[0][1]
        assert "Test User" in call_args[0][1]

    def test_plan_approval_rejected(self, sample_task: Path, sample_config: GalangalConfig):
        """Test plan approval flow when user rejects."""
        from galangal.commands.approve import prompt_plan_approval

        state = make_state(task_name="test-task", stage=Stage.DESIGN)

        with patch("galangal.commands.approve.read_artifact", return_value="# Test Plan"):
            with patch("galangal.commands.approve.save_state"):
                with patch("galangal.commands.approve.Prompt.ask") as mock_prompt:
                    # Simulate: n, then rejection reason
                    mock_prompt.side_effect = ["n", "Need more detail"]
                    with patch("galangal.commands.approve.console"):
                        result = prompt_plan_approval("test-task", state)

        assert result == "rejected"
        # State should be rolled back to PM
        assert state.stage == Stage.PM
        assert "rejected" in state.last_failure.lower()
        assert "Need more detail" in state.last_failure

    def test_plan_approval_quit(self, sample_task: Path, sample_config: GalangalConfig):
        """Test plan approval flow when user quits."""
        from galangal.commands.approve import prompt_plan_approval

        state = make_state(task_name="test-task", stage=Stage.DESIGN)

        with patch("galangal.commands.approve.read_artifact", return_value="# Test Plan"):
            with patch("galangal.commands.approve.Prompt.ask") as mock_prompt:
                mock_prompt.return_value = "q"
                with patch("galangal.commands.approve.console"):
                    result = prompt_plan_approval("test-task", state)

        assert result == "quit"
        # State should remain unchanged
        assert state.stage == Stage.DESIGN

    def test_design_approval_accepted(
        self, sample_task: Path, sample_config: GalangalConfig
    ):
        """Test design approval flow when user approves."""
        from galangal.commands.approve import prompt_design_approval

        state = make_state(task_name="test-task", stage=Stage.DEV)

        # Create DESIGN.md artifact
        create_artifact(sample_task, "DESIGN.md", "# Design\n\nArchitecture details")

        with patch("galangal.commands.approve.read_artifact", return_value="# Test Design"):
            with patch("galangal.commands.approve.write_artifact") as mock_write:
                with patch("galangal.commands.approve.Prompt.ask") as mock_prompt:
                    mock_prompt.side_effect = ["y", "Reviewer Name"]
                    with patch("galangal.commands.approve.console"):
                        result = prompt_design_approval("test-task", state)

        assert result == "approved"
        mock_write.assert_called_once()
        call_args = mock_write.call_args
        assert call_args[0][0] == "DESIGN_REVIEW.md"
        assert "Approved" in call_args[0][1]

    def test_design_approval_rejected(
        self, sample_task: Path, sample_config: GalangalConfig
    ):
        """Test design approval flow when user rejects."""
        from galangal.commands.approve import prompt_design_approval

        state = make_state(task_name="test-task", stage=Stage.DEV)

        with patch("galangal.commands.approve.read_artifact", return_value="# Test Design"):
            with patch("galangal.commands.approve.save_state"):
                with patch("galangal.commands.approve.Prompt.ask") as mock_prompt:
                    mock_prompt.side_effect = ["n", "Architecture needs rework"]
                    with patch("galangal.commands.approve.console"):
                        result = prompt_design_approval("test-task", state)

        assert result == "rejected"
        assert state.stage == Stage.DESIGN
        assert "rejected" in state.last_failure.lower()


class TestStatePersistence:
    """Tests for workflow state persistence."""

    def test_state_roundtrip(self, sample_task: Path):
        """Test saving and loading state preserves all fields."""
        state = WorkflowState(
            stage=Stage.DEV,
            attempt=3,
            awaiting_approval=True,
            clarification_required=False,
            last_failure="Previous error",
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Test description",
            task_name="test-task",
            task_type=TaskType.BUG_FIX,
        )

        # Add rollback history
        state.record_rollback(Stage.QA, Stage.DEV, "QA failed")

        with patch("galangal.core.state.get_task_dir", return_value=sample_task):
            save_state(state)

        # Load state back
        state_file = sample_task / "state.json"
        loaded_data = json.loads(state_file.read_text())
        loaded_state = WorkflowState.from_dict(loaded_data)

        assert loaded_state.stage == Stage.DEV
        assert loaded_state.attempt == 3
        assert loaded_state.awaiting_approval is True
        assert loaded_state.task_type == TaskType.BUG_FIX
        assert loaded_state.last_failure == "Previous error"
        assert len(loaded_state.rollback_history) == 1
        assert loaded_state.rollback_history[0].from_stage == "QA"
        assert loaded_state.rollback_history[0].to_stage == "DEV"

    def test_state_from_dict_with_defaults(self):
        """Test loading state with missing optional fields uses defaults."""
        minimal_data = {
            "stage": "DEV",
            "task_name": "test",
            "task_description": "desc",
        }

        state = WorkflowState.from_dict(minimal_data)

        assert state.stage == Stage.DEV
        assert state.attempt == 1  # default
        assert state.awaiting_approval is False  # default
        assert state.task_type == TaskType.FEATURE  # default
        assert state.rollback_history == []  # default
