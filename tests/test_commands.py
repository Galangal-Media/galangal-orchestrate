"""Tests for CLI commands."""

import argparse
from datetime import datetime, timezone
from unittest.mock import patch

from galangal.core.state import Stage, TaskType, WorkflowState


def make_state(
    task_name: str = "test-task",
    stage: Stage = Stage.DEV,
    attempt: int = 1,
    task_type: TaskType = TaskType.FEATURE,
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
        task_type=task_type,
    )


class TestCmdList:
    """Tests for the list command."""

    def test_list_returns_zero(self):
        """Test list command returns 0."""
        from galangal.commands.list import cmd_list

        args = argparse.Namespace()

        with patch("galangal.commands.list.list_tasks", return_value=[]):
            with patch("galangal.commands.list.get_active_task", return_value=None):
                with patch("galangal.commands.list.display_task_list"):
                    result = cmd_list(args)
                    assert result == 0

    def test_list_shows_active_task_hint(self):
        """Test list shows active task indicator when active task exists."""
        from galangal.commands.list import cmd_list

        args = argparse.Namespace()
        tasks = [{"name": "task-1", "stage": "DEV"}, {"name": "task-2", "stage": "QA"}]

        with patch("galangal.commands.list.list_tasks", return_value=tasks):
            with patch("galangal.commands.list.get_active_task", return_value="task-1"):
                with patch("galangal.commands.list.display_task_list") as mock_display:
                    with patch("galangal.commands.list.console.print"):
                        result = cmd_list(args)
                        assert result == 0
                        mock_display.assert_called_once_with(tasks, "task-1")


class TestCmdStatus:
    """Tests for the status command."""

    def test_status_no_active_task(self):
        """Test status with no active task."""
        from galangal.commands.status import cmd_status

        args = argparse.Namespace()

        with patch("galangal.commands.status.get_active_task", return_value=None):
            with patch("galangal.commands.status.print_info") as mock_info:
                result = cmd_status(args)
                assert result == 0
                mock_info.assert_called_once()

    def test_status_state_load_failure(self):
        """Test status when state cannot be loaded."""
        from galangal.commands.status import cmd_status

        args = argparse.Namespace()

        with patch("galangal.commands.status.get_active_task", return_value="test-task"):
            with patch("galangal.core.state.load_state", return_value=None):
                with patch("galangal.commands.status.print_error") as mock_error:
                    result = cmd_status(args)
                    assert result == 1
                    mock_error.assert_called_once()

    def test_status_displays_task_info(self):
        """Test status displays task information."""
        from galangal.commands.status import cmd_status

        args = argparse.Namespace()
        state = make_state(task_name="test-task", stage=Stage.DEV)

        with patch("galangal.commands.status.get_active_task", return_value="test-task"):
            with patch("galangal.core.state.load_state", return_value=state):
                with patch("galangal.commands.status.artifact_exists", return_value=False):
                    with patch("galangal.commands.status.display_status") as mock_display:
                        result = cmd_status(args)
                        assert result == 0
                        mock_display.assert_called_once()
                        call_kwargs = mock_display.call_args.kwargs
                        assert call_kwargs["task_name"] == "test-task"
                        assert call_kwargs["stage"] == Stage.DEV


class TestCmdSkipTo:
    """Tests for the skip-to command."""

    def test_skip_to_no_active_task(self):
        """Test skip-to with no active task."""
        from galangal.commands.skip import cmd_skip_to

        args = argparse.Namespace(stage="DEV", force=False, resume=False)

        with patch(
            "galangal.commands.skip.ensure_active_task_with_state", return_value=(None, None)
        ):
            result = cmd_skip_to(args)
            assert result == 1

    def test_skip_to_invalid_stage(self):
        """Test skip-to with invalid stage name."""
        from galangal.commands.skip import cmd_skip_to

        args = argparse.Namespace(stage="INVALID", force=False, resume=False)
        state = make_state(stage=Stage.DEV)

        with patch(
            "galangal.commands.skip.ensure_active_task_with_state",
            return_value=("test-task", state),
        ):
            with patch("galangal.ui.console.print_error") as mock_error:
                with patch("galangal.commands.skip.console.print"):
                    result = cmd_skip_to(args)
                    assert result == 1
                    assert "invalid" in mock_error.call_args[0][0].lower()

    def test_skip_to_complete_not_allowed(self):
        """Test skip-to COMPLETE is not allowed."""
        from galangal.commands.skip import cmd_skip_to

        args = argparse.Namespace(stage="COMPLETE", force=False, resume=False)
        state = make_state(stage=Stage.DEV)

        with patch(
            "galangal.commands.skip.ensure_active_task_with_state",
            return_value=("test-task", state),
        ):
            with patch("galangal.ui.console.print_error") as mock_error:
                result = cmd_skip_to(args)
                assert result == 1
                assert "complete" in mock_error.call_args[0][0].lower()

    def test_skip_to_with_force(self):
        """Test skip-to with --force flag."""
        from galangal.commands.skip import cmd_skip_to

        args = argparse.Namespace(stage="QA", force=True, resume=False)
        state = make_state(stage=Stage.DEV)

        with patch(
            "galangal.commands.skip.ensure_active_task_with_state",
            return_value=("test-task", state),
        ):
            with patch("galangal.commands.skip.save_state") as mock_save:
                with patch("galangal.commands.skip.print_success"):
                    with patch("galangal.commands.skip.console.print"):
                        result = cmd_skip_to(args)
                        assert result == 0
                        # Verify state was updated
                        assert state.stage == Stage.QA
                        assert state.attempt == 1
                        mock_save.assert_called_once()

    def test_skip_to_cancelled(self):
        """Test skip-to cancelled by user."""
        from galangal.commands.skip import cmd_skip_to

        args = argparse.Namespace(stage="QA", force=False, resume=False)
        state = make_state(stage=Stage.DEV)

        with patch(
            "galangal.commands.skip.ensure_active_task_with_state",
            return_value=("test-task", state),
        ):
            with patch("galangal.commands.skip.Prompt.ask", return_value="n"):
                with patch("galangal.commands.skip.print_info") as mock_info:
                    with patch("galangal.commands.skip.console.print"):
                        result = cmd_skip_to(args)
                        assert result == 0
                        assert "cancel" in mock_info.call_args[0][0].lower()


class TestCreateTaskBranch:
    """Tests for create_task_branch function."""

    def test_creates_new_branch(self):
        """Test creating a new branch when it doesn't exist."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import create_task_branch

        config = GalangalConfig()

        with patch("galangal.core.tasks.get_config", return_value=config):
            # Branch doesn't exist (empty output)
            with patch("galangal.core.tasks.run_command") as mock_run:
                mock_run.side_effect = [
                    (0, "", ""),  # git branch --list returns empty
                    (0, "", ""),  # git checkout -b succeeds
                ]
                success, msg = create_task_branch("test-task")

                assert success is True
                assert "Created branch" in msg
                # Verify checkout -b was called
                assert mock_run.call_count == 2
                assert "-b" in str(mock_run.call_args_list[1])

    def test_checks_out_existing_branch(self):
        """Test that existing branch is checked out instead of just returning success."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import create_task_branch

        config = GalangalConfig()

        with patch("galangal.core.tasks.get_config", return_value=config):
            with patch("galangal.core.tasks.run_command") as mock_run:
                mock_run.side_effect = [
                    (0, "galangal/test-task", ""),  # Branch exists
                    (0, "", ""),  # git checkout succeeds
                ]
                success, msg = create_task_branch("test-task")

                assert success is True
                assert "Checked out existing branch" in msg
                # Verify checkout (not checkout -b) was called
                assert mock_run.call_count == 2
                checkout_call = mock_run.call_args_list[1]
                assert "checkout" in str(checkout_call)
                assert "-b" not in str(checkout_call)

    def test_existing_branch_checkout_failure(self):
        """Test error handling when existing branch checkout fails."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import create_task_branch

        config = GalangalConfig()

        with patch("galangal.core.tasks.get_config", return_value=config):
            with patch("galangal.core.tasks.run_command") as mock_run:
                mock_run.side_effect = [
                    (0, "galangal/test-task", ""),  # Branch exists
                    (1, "", "error: cannot checkout"),  # checkout fails
                ]
                success, msg = create_task_branch("test-task")

                assert success is False
                assert "checkout failed" in msg


class TestBaseBranchCheck:
    """Tests for base branch checking functions."""

    def test_is_on_base_branch_true(self):
        """Test is_on_base_branch returns True when on base branch."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import is_on_base_branch

        config = GalangalConfig()  # default base_branch is "main"

        with patch("galangal.core.tasks.get_config", return_value=config):
            with patch("galangal.core.tasks.get_current_branch", return_value="main"):
                is_on_base, current, base = is_on_base_branch()

                assert is_on_base is True
                assert current == "main"
                assert base == "main"

    def test_is_on_base_branch_false(self):
        """Test is_on_base_branch returns False when on different branch."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import is_on_base_branch

        config = GalangalConfig()

        with patch("galangal.core.tasks.get_config", return_value=config):
            with patch("galangal.core.tasks.get_current_branch", return_value="feature-branch"):
                is_on_base, current, base = is_on_base_branch()

                assert is_on_base is False
                assert current == "feature-branch"
                assert base == "main"

    def test_switch_to_base_branch_success(self):
        """Test switch_to_base_branch succeeds."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import switch_to_base_branch

        config = GalangalConfig()

        with patch("galangal.core.tasks.get_config", return_value=config):
            with patch("galangal.core.tasks.run_command", return_value=(0, "", "")):
                success, msg = switch_to_base_branch()

                assert success is True
                assert "Switched to main" in msg

    def test_switch_to_base_branch_failure(self):
        """Test switch_to_base_branch handles failure."""
        from galangal.config.schema import GalangalConfig
        from galangal.core.tasks import switch_to_base_branch

        config = GalangalConfig()

        with patch("galangal.core.tasks.get_config", return_value=config):
            with patch(
                "galangal.core.tasks.run_command",
                return_value=(1, "", "error: uncommitted changes"),
            ):
                success, msg = switch_to_base_branch()

                assert success is False
                assert "Failed to switch" in msg
