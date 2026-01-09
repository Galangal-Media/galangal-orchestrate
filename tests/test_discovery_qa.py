"""
Tests for the Discovery Q&A feature.

This module tests:
- State Q&A field serialization/deserialization
- Question parsing from AI output
- Discovery log artifact writing
- TUI Q&A modals
- Prompt builder discovery methods
- TaskTypeSettings config
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from galangal.config.schema import GalangalConfig, TaskTypeSettings
from galangal.core.state import Stage, TaskType, WorkflowState


# -----------------------------------------------------------------------------
# State Q&A Fields Tests
# -----------------------------------------------------------------------------


class TestStateQAFields:
    """Tests for WorkflowState Q&A tracking fields."""

    def test_state_with_qa_fields_to_dict(self):
        """Test that Q&A fields are included in to_dict output."""
        state = WorkflowState(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Test task",
            task_name="test-task",
            task_type=TaskType.FEATURE,
            pm_subphase="questioning",
            qa_rounds=[{"questions": ["Q1?"], "answers": ["A1"]}],
            qa_complete=False,
        )

        data = state.to_dict()

        assert data["pm_subphase"] == "questioning"
        assert data["qa_rounds"] == [{"questions": ["Q1?"], "answers": ["A1"]}]
        assert data["qa_complete"] is False

    def test_state_from_dict_with_qa_fields(self):
        """Test that Q&A fields are restored from dict."""
        data = {
            "stage": "PM",
            "attempt": 1,
            "awaiting_approval": False,
            "clarification_required": False,
            "last_failure": None,
            "started_at": "2024-01-01T00:00:00Z",
            "task_description": "Test",
            "task_name": "test",
            "task_type": "feature",
            "pm_subphase": "specifying",
            "qa_rounds": [
                {"questions": ["Q1?", "Q2?"], "answers": ["A1", "A2"]},
                {"questions": ["Q3?"], "answers": ["A3"]},
            ],
            "qa_complete": True,
        }

        state = WorkflowState.from_dict(data)

        assert state.pm_subphase == "specifying"
        assert len(state.qa_rounds) == 2
        assert state.qa_rounds[0]["questions"] == ["Q1?", "Q2?"]
        assert state.qa_complete is True

    def test_state_from_dict_without_qa_fields_uses_defaults(self):
        """Test that missing Q&A fields default to None/False."""
        data = {
            "stage": "PM",
            "attempt": 1,
            "awaiting_approval": False,
            "clarification_required": False,
            "last_failure": None,
            "started_at": "2024-01-01T00:00:00Z",
            "task_description": "Test",
            "task_name": "test",
            "task_type": "feature",
        }

        state = WorkflowState.from_dict(data)

        assert state.pm_subphase is None
        assert state.qa_rounds is None
        assert state.qa_complete is False

    def test_state_qa_fields_roundtrip(self):
        """Test that Q&A fields survive JSON roundtrip."""
        original = WorkflowState(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Test task",
            task_name="test-task",
            task_type=TaskType.FEATURE,
            pm_subphase="analyzing",
            qa_rounds=[
                {"questions": ["What auth?", "What scope?"], "answers": ["JWT", "API only"]},
            ],
            qa_complete=False,
        )

        # Simulate save/load
        json_str = json.dumps(original.to_dict())
        restored = WorkflowState.from_dict(json.loads(json_str))

        assert restored.pm_subphase == original.pm_subphase
        assert restored.qa_rounds == original.qa_rounds
        assert restored.qa_complete == original.qa_complete


# -----------------------------------------------------------------------------
# Question Parsing Tests
# -----------------------------------------------------------------------------


class TestQuestionParsing:
    """Tests for _parse_discovery_questions function."""

    def test_parse_numbered_questions(self):
        """Test parsing numbered question format."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = """
# DISCOVERY_QUESTIONS

1. What authentication method should be used?
2. Should this support mobile clients?
3. What's the expected user volume?
"""
        questions = _parse_discovery_questions(output)

        assert len(questions) == 3
        assert questions[0] == "What authentication method should be used?"
        assert questions[1] == "Should this support mobile clients?"
        assert questions[2] == "What's the expected user volume?"

    def test_parse_questions_with_parenthesis_numbers(self):
        """Test parsing questions with parenthesis numbering."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = """
# DISCOVERY_QUESTIONS

1) What framework to use?
2) How many users expected?
"""
        questions = _parse_discovery_questions(output)

        assert len(questions) == 2
        assert questions[0] == "What framework to use?"
        assert questions[1] == "How many users expected?"

    def test_parse_bullet_point_questions(self):
        """Test parsing bullet point format."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = """
# DISCOVERY_QUESTIONS

- What database should be used?
- Should we implement caching?
"""
        questions = _parse_discovery_questions(output)

        assert len(questions) == 2
        assert questions[0] == "What database should be used?"
        assert questions[1] == "Should we implement caching?"

    def test_parse_no_questions_marker(self):
        """Test that NO_QUESTIONS marker returns empty list."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = """
# NO_QUESTIONS

The brief covers:
- Clear requirements
- Defined scope

Ready to proceed with specification.
"""
        questions = _parse_discovery_questions(output)

        assert questions == []

    def test_parse_no_questions_marker_without_space(self):
        """Test NO_QUESTIONS marker without space."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = "#NO_QUESTIONS\nBrief is comprehensive."
        questions = _parse_discovery_questions(output)

        assert questions == []

    def test_parse_empty_output(self):
        """Test parsing empty output."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        questions = _parse_discovery_questions("")

        assert questions == []

    def test_parse_output_without_header(self):
        """Test parsing output without DISCOVERY_QUESTIONS header."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = """
Here are some thoughts:
1. Consider the architecture
2. Think about scaling
"""
        questions = _parse_discovery_questions(output)

        # Without the header, questions shouldn't be captured
        assert questions == []

    def test_parse_ignores_content_before_header(self):
        """Test that content before DISCOVERY_QUESTIONS header is ignored."""
        from galangal.core.workflow.tui_runner import _parse_discovery_questions

        output = """
Some preamble text here.
This should be ignored.

# DISCOVERY_QUESTIONS

1. Actual question here?
"""
        questions = _parse_discovery_questions(output)

        assert len(questions) == 1
        assert questions[0] == "Actual question here?"


# -----------------------------------------------------------------------------
# Discovery Log Writing Tests
# -----------------------------------------------------------------------------


class TestDiscoveryLogWriting:
    """Tests for _write_discovery_log function."""

    def test_write_single_round(self, tmp_path, monkeypatch):
        """Test writing a discovery log with one Q&A round."""
        from galangal.core.workflow.tui_runner import _write_discovery_log

        # Setup task directory
        task_dir = tmp_path / "galangal-tasks" / "test-task"
        task_dir.mkdir(parents=True)

        # Mock get_task_dir to return our temp path
        monkeypatch.setattr(
            "galangal.core.artifacts.get_task_dir",
            lambda name: task_dir,
        )

        qa_rounds = [
            {"questions": ["What auth?", "What scope?"], "answers": ["JWT", "API only"]}
        ]

        _write_discovery_log("test-task", qa_rounds)

        log_path = task_dir / "DISCOVERY_LOG.md"
        assert log_path.exists()

        content = log_path.read_text()
        assert "# Discovery Log" in content
        assert "## Round 1" in content
        assert "### Questions" in content
        assert "1. What auth?" in content
        assert "2. What scope?" in content
        assert "### Answers" in content
        assert "1. JWT" in content
        assert "2. API only" in content

    def test_write_multiple_rounds(self, tmp_path, monkeypatch):
        """Test writing a discovery log with multiple Q&A rounds."""
        from galangal.core.workflow.tui_runner import _write_discovery_log

        task_dir = tmp_path / "galangal-tasks" / "test-task"
        task_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "galangal.core.artifacts.get_task_dir",
            lambda name: task_dir,
        )

        qa_rounds = [
            {"questions": ["Q1?"], "answers": ["A1"]},
            {"questions": ["Q2?", "Q3?"], "answers": ["A2", "A3"]},
        ]

        _write_discovery_log("test-task", qa_rounds)

        content = (task_dir / "DISCOVERY_LOG.md").read_text()
        assert "## Round 1" in content
        assert "## Round 2" in content
        assert "1. Q1?" in content
        assert "1. Q2?" in content
        assert "2. Q3?" in content


# -----------------------------------------------------------------------------
# TUI Q&A Modal Tests
# -----------------------------------------------------------------------------


class TestQuestionAnswerModal:
    """Tests for QuestionAnswerModal."""

    @pytest.mark.asyncio
    async def test_modal_displays_questions(self):
        """Test that modal displays all questions."""
        from galangal.ui.tui import WorkflowTUIApp

        app = WorkflowTUIApp(task_name="test", initial_stage="PM")

        async with app.run_test() as pilot:
            result_holder = []

            # Show the Q&A modal via callback pattern
            from galangal.ui.tui.modals import QuestionAnswerModal

            questions = ["What auth method?", "What database?"]
            modal = QuestionAnswerModal(questions)
            app.push_screen(modal, lambda r: result_holder.append(r))

            await pilot.pause()
            await pilot.pause()

            # Modal should be active - verify by checking we can interact with it
            # Type an answer and press enter to confirm modal is accepting input
            await pilot.press("t", "e", "s", "t")
            await pilot.press("enter")
            await pilot.pause()

            # Type second answer
            await pilot.press("t", "e", "s", "t", "2")
            await pilot.press("enter")
            await pilot.pause()

            # Should have received both answers
            assert len(result_holder) == 1
            assert result_holder[0] == ["test", "test2"]

    @pytest.mark.asyncio
    async def test_modal_collects_answers_sequentially(self):
        """Test that modal collects answers one by one."""
        from galangal.ui.tui import WorkflowTUIApp

        app = WorkflowTUIApp(task_name="test", initial_stage="PM")

        async with app.run_test() as pilot:
            result_holder = []

            from galangal.ui.tui.modals import QuestionAnswerModal

            questions = ["Q1?", "Q2?"]
            modal = QuestionAnswerModal(questions)
            app.push_screen(modal, lambda r: result_holder.append(r))

            await pilot.pause()
            await pilot.pause()

            # Answer first question
            await pilot.press(*list("answer1"))
            await pilot.press("enter")
            await pilot.pause()

            # Answer second question
            await pilot.press(*list("answer2"))
            await pilot.press("enter")
            await pilot.pause()

            assert result_holder == [["answer1", "answer2"]]

    @pytest.mark.asyncio
    async def test_modal_escape_cancels(self):
        """Test that Escape cancels the modal."""
        from galangal.ui.tui import WorkflowTUIApp

        app = WorkflowTUIApp(task_name="test", initial_stage="PM")

        async with app.run_test() as pilot:
            result_holder = []

            from galangal.ui.tui.modals import QuestionAnswerModal

            questions = ["Q1?"]
            modal = QuestionAnswerModal(questions)
            app.push_screen(modal, lambda r: result_holder.append(r))

            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            assert result_holder == [None]


class TestUserQuestionsModal:
    """Tests for UserQuestionsModal."""

    @pytest.mark.asyncio
    async def test_modal_parses_multiline_questions(self):
        """Test that modal parses questions from multiline input."""
        from galangal.ui.tui import WorkflowTUIApp

        app = WorkflowTUIApp(task_name="test", initial_stage="PM")

        async with app.run_test() as pilot:
            result_holder = []

            from galangal.ui.tui.modals import UserQuestionsModal

            modal = UserQuestionsModal()
            app.push_screen(modal, lambda r: result_holder.append(r))

            await pilot.pause()
            await pilot.pause()

            # Type questions (each on new line)
            await pilot.press(*list("Question 1?"))
            await pilot.press("enter")
            await pilot.press(*list("Question 2?"))
            await pilot.pause()

            # Submit with Ctrl+S
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert result_holder == [["Question 1?", "Question 2?"]]

    @pytest.mark.asyncio
    async def test_modal_escape_returns_none(self):
        """Test that Escape returns None."""
        from galangal.ui.tui import WorkflowTUIApp

        app = WorkflowTUIApp(task_name="test", initial_stage="PM")

        async with app.run_test() as pilot:
            result_holder = []

            from galangal.ui.tui.modals import UserQuestionsModal

            modal = UserQuestionsModal()
            app.push_screen(modal, lambda r: result_holder.append(r))

            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            assert result_holder == [None]


# -----------------------------------------------------------------------------
# Prompt Builder Tests
# -----------------------------------------------------------------------------


class TestPromptBuilderDiscovery:
    """Tests for PromptBuilder discovery methods."""

    def test_get_prompt_by_name_returns_default(self, tmp_path, monkeypatch):
        """Test that get_prompt_by_name returns default prompt."""
        from galangal.prompts.builder import PromptBuilder

        # Setup minimal config
        galangal_dir = tmp_path / ".galangal"
        galangal_dir.mkdir()
        (galangal_dir / "config.yaml").write_text("project:\n  name: Test")
        (galangal_dir / "prompts").mkdir()

        monkeypatch.chdir(tmp_path)

        builder = PromptBuilder()
        prompt = builder.get_prompt_by_name("pm_questions")

        assert "PM Discovery" in prompt or "clarifying questions" in prompt.lower()

    def test_build_discovery_prompt_includes_brief(self, tmp_path, monkeypatch):
        """Test that discovery prompt includes the task brief."""
        from galangal.prompts.builder import PromptBuilder

        galangal_dir = tmp_path / ".galangal"
        galangal_dir.mkdir()
        (galangal_dir / "config.yaml").write_text("project:\n  name: Test")
        (galangal_dir / "prompts").mkdir()

        monkeypatch.chdir(tmp_path)

        state = WorkflowState(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Add user authentication with OAuth2",
            task_name="test-task",
            task_type=TaskType.FEATURE,
        )

        builder = PromptBuilder()
        prompt = builder.build_discovery_prompt(state)

        assert "Add user authentication with OAuth2" in prompt
        assert "test-task" in prompt

    def test_build_discovery_prompt_includes_qa_history(self, tmp_path, monkeypatch):
        """Test that discovery prompt includes previous Q&A history."""
        from galangal.prompts.builder import PromptBuilder

        galangal_dir = tmp_path / ".galangal"
        galangal_dir.mkdir()
        (galangal_dir / "config.yaml").write_text("project:\n  name: Test")
        (galangal_dir / "prompts").mkdir()

        monkeypatch.chdir(tmp_path)

        state = WorkflowState(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Test task",
            task_name="test-task",
            task_type=TaskType.FEATURE,
        )

        qa_history = [
            {"questions": ["What auth?"], "answers": ["JWT"]},
        ]

        builder = PromptBuilder()
        prompt = builder.build_discovery_prompt(state, qa_history)

        assert "Round 1" in prompt
        assert "What auth?" in prompt
        assert "JWT" in prompt

    def test_build_discovery_prompt_no_history(self, tmp_path, monkeypatch):
        """Test discovery prompt when no Q&A history exists."""
        from galangal.prompts.builder import PromptBuilder

        galangal_dir = tmp_path / ".galangal"
        galangal_dir.mkdir()
        (galangal_dir / "config.yaml").write_text("project:\n  name: Test")
        (galangal_dir / "prompts").mkdir()

        monkeypatch.chdir(tmp_path)

        state = WorkflowState(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Test task",
            task_name="test-task",
            task_type=TaskType.FEATURE,
        )

        builder = PromptBuilder()
        prompt = builder.build_discovery_prompt(state, qa_history=None)

        assert "first round" in prompt.lower() or "None" in prompt


# -----------------------------------------------------------------------------
# Config Tests
# -----------------------------------------------------------------------------


class TestTaskTypeSettings:
    """Tests for TaskTypeSettings configuration."""

    def test_task_type_settings_default(self):
        """Test that TaskTypeSettings has correct defaults."""
        settings = TaskTypeSettings()

        assert settings.skip_discovery is False

    def test_task_type_settings_skip_discovery_true(self):
        """Test TaskTypeSettings with skip_discovery enabled."""
        settings = TaskTypeSettings(skip_discovery=True)

        assert settings.skip_discovery is True

    def test_config_with_task_type_settings(self):
        """Test GalangalConfig with task_type_settings."""
        config = GalangalConfig(
            task_type_settings={
                "bugfix": TaskTypeSettings(skip_discovery=True),
                "feature": TaskTypeSettings(skip_discovery=False),
            }
        )

        assert config.task_type_settings["bugfix"].skip_discovery is True
        assert config.task_type_settings["feature"].skip_discovery is False

    def test_config_task_type_settings_default_empty(self):
        """Test that task_type_settings defaults to empty dict."""
        config = GalangalConfig()

        assert config.task_type_settings == {}

    def test_config_from_yaml_with_task_type_settings(self, tmp_path):
        """Test loading config with task_type_settings from YAML."""
        from galangal.config.loader import load_config, set_project_root

        # Set up project structure
        galangal_dir = tmp_path / ".galangal"
        galangal_dir.mkdir()

        config_content = """
project:
  name: Test Project

task_type_settings:
  bugfix:
    skip_discovery: true
  hotfix:
    skip_discovery: true
"""
        config_path = galangal_dir / "config.yaml"
        config_path.write_text(config_content)

        # Set project root and load config
        set_project_root(tmp_path)
        config = load_config(tmp_path)

        assert config.task_type_settings["bugfix"].skip_discovery is True
        assert config.task_type_settings["hotfix"].skip_discovery is True


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


class TestDiscoveryIntegration:
    """Integration tests for the discovery Q&A flow."""

    def test_pm_stage_includes_discovery_log_artifact(self):
        """Test that PM stage metadata includes DISCOVERY_LOG.md."""
        from galangal.core.state import STAGE_METADATA, Stage

        pm_metadata = STAGE_METADATA[Stage.PM]

        assert "DISCOVERY_LOG.md" in pm_metadata.produces_artifacts

    def test_state_qa_complete_persists(self, tmp_path):
        """Test that qa_complete flag persists across save/load."""
        task_dir = tmp_path / "galangal-tasks" / "test-task"
        task_dir.mkdir(parents=True)

        state = WorkflowState(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description="Test",
            task_name="test-task",
            task_type=TaskType.FEATURE,
            qa_complete=True,
            qa_rounds=[{"questions": ["Q?"], "answers": ["A"]}],
        )

        # Save
        state_path = task_dir / "state.json"
        state_path.write_text(json.dumps(state.to_dict(), indent=2))

        # Load
        loaded_data = json.loads(state_path.read_text())
        loaded_state = WorkflowState.from_dict(loaded_data)

        assert loaded_state.qa_complete is True
        assert loaded_state.qa_rounds == [{"questions": ["Q?"], "answers": ["A"]}]
