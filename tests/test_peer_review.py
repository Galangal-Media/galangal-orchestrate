"""
Tests for the peer review feature.

Tests cover:
- Configuration defaults and schema
- Engine: _should_run_peer_review logic
- Engine: execute_peer_review with mock backends
- Prompt building for peer review
- JSON output parsing for Codex backend
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from galangal.config.schema import GalangalConfig, PeerReviewConfig
from galangal.core.state import Stage, TaskType, WorkflowState
from galangal.core.workflow.engine import EventType, WorkflowEngine
from galangal.prompts.builder import PromptBuilder
from galangal.results import StageResult


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


# =============================================================================
# Config tests
# =============================================================================


class TestPeerReviewConfig:
    def test_defaults(self):
        """PeerReviewConfig is disabled by default with auto_accept on."""
        config = PeerReviewConfig()
        assert config.enabled is False
        assert config.backend == "codex"
        assert config.stages == ["PM", "DESIGN"]
        assert config.auto_accept is True
        assert config.max_auto_loops == 5

    def test_enabled_in_galangal_config(self):
        """peer_review field exists on GalangalConfig with defaults."""
        config = GalangalConfig()
        assert config.peer_review.enabled is False
        assert config.peer_review.backend == "codex"

    def test_custom_stages(self):
        """Can customize which stages get peer reviewed."""
        config = PeerReviewConfig(enabled=True, stages=["PM"])
        assert config.stages == ["PM"]

    def test_auto_accept_disabled(self):
        """Can disable auto_accept to restore manual flow."""
        config = PeerReviewConfig(auto_accept=False)
        assert config.auto_accept is False

    def test_custom_max_auto_loops(self):
        """Can customize the max auto-accept loop count."""
        config = PeerReviewConfig(max_auto_loops=3)
        assert config.max_auto_loops == 3


# =============================================================================
# Engine: _should_run_peer_review
# =============================================================================


class TestShouldRunPeerReview:
    def _make_engine(self, enabled=False, stages=None, stage=Stage.PM):
        state = make_state(stage=stage)
        config = GalangalConfig(
            peer_review=PeerReviewConfig(
                enabled=enabled,
                stages=stages or ["PM", "DESIGN"],
            ),
        )
        return WorkflowEngine(state, config)

    def test_disabled(self):
        """Returns False when peer review is disabled."""
        engine = self._make_engine(enabled=False)
        assert engine._should_run_peer_review(Stage.PM) is False

    def test_enabled_configured_stage(self):
        """Returns True for a configured stage when enabled."""
        engine = self._make_engine(enabled=True, stages=["PM", "DESIGN"])
        with patch("galangal.core.workflow.engine.artifact_exists", return_value=False):
            assert engine._should_run_peer_review(Stage.PM) is True

    def test_skips_unconfigured_stage(self):
        """Returns False for stages not in the configured list."""
        engine = self._make_engine(enabled=True, stages=["PM"])
        assert engine._should_run_peer_review(Stage.DEV) is False

    def test_skips_if_artifact_exists(self):
        """Returns False if peer review artifact already exists (idempotency)."""
        engine = self._make_engine(enabled=True, stages=["PM"])
        with patch("galangal.core.workflow.engine.artifact_exists", return_value=True):
            assert engine._should_run_peer_review(Stage.PM) is False


# =============================================================================
# Engine: execute_peer_review
# =============================================================================


class TestExecutePeerReview:
    def _make_engine(self, stage=Stage.PM, backend_name="codex"):
        state = make_state(stage=stage)
        config = GalangalConfig(
            peer_review=PeerReviewConfig(
                enabled=True,
                backend=backend_name,
            ),
        )
        return WorkflowEngine(state, config)

    def test_approve(self, tmp_path):
        """Reviewer approves - returns APPROVE decision."""
        engine = self._make_engine()
        tui_app = MagicMock()

        # Mock backend returning APPROVE JSON
        mock_result = StageResult.create_success(
            "Review complete",
            output=json.dumps({
                "decision": "APPROVE",
                "review_notes": "Looks good!",
            }),
        )
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = mock_result
        mock_backend.read_only = True
        mock_backend.name = "codex"

        with (
            patch("galangal.ai.is_backend_available", return_value=True),
            patch("galangal.ai.get_backend_with_fallback", return_value=mock_backend),
            patch("galangal.core.artifacts.write_artifact"),
            patch("galangal.core.state.get_task_dir", return_value=tmp_path),
        ):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "APPROVE"
        assert "Looks good!" in notes

    def test_request_changes(self, tmp_path):
        """Reviewer requests changes - returns REQUEST_CHANGES decision."""
        engine = self._make_engine()
        tui_app = MagicMock()

        mock_result = StageResult.create_success(
            "Review complete",
            output=json.dumps({
                "decision": "REQUEST_CHANGES",
                "review_notes": "Missing acceptance criteria",
            }),
        )
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = mock_result
        mock_backend.read_only = True
        mock_backend.name = "codex"

        with (
            patch("galangal.ai.is_backend_available", return_value=True),
            patch("galangal.ai.get_backend_with_fallback", return_value=mock_backend),
            patch("galangal.core.artifacts.write_artifact"),
            patch("galangal.core.state.get_task_dir", return_value=tmp_path),
        ):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "REQUEST_CHANGES"
        assert "Missing acceptance criteria" in notes

    def test_backend_unavailable(self):
        """Gracefully returns APPROVE when backend is unavailable."""
        engine = self._make_engine()
        tui_app = MagicMock()

        with patch("galangal.ai.is_backend_available", return_value=False):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "APPROVE"
        assert notes == ""

    def test_backend_invocation_failure(self, tmp_path):
        """Gracefully returns APPROVE when backend invocation fails."""
        engine = self._make_engine()
        tui_app = MagicMock()

        mock_result = StageResult.validation_failed("Backend error")
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = mock_result
        mock_backend.read_only = True
        mock_backend.name = "codex"

        with (
            patch("galangal.ai.is_backend_available", return_value=True),
            patch("galangal.ai.get_backend_with_fallback", return_value=mock_backend),
            patch("galangal.core.state.get_task_dir", return_value=tmp_path),
        ):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "APPROVE"

    def test_markdown_decision_parsing(self, tmp_path):
        """Non-read-only backends: parses DECISION from markdown output."""
        engine = self._make_engine()
        tui_app = MagicMock()

        markdown_output = """## Review Notes
The spec looks good overall.

## Issues
- Minor: naming could be clearer

# DECISION: REQUEST_CHANGES
"""
        mock_result = StageResult.create_success("Done", output=markdown_output)
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = mock_result
        mock_backend.read_only = False  # Not read-only = markdown parsing
        mock_backend.name = "claude"

        with (
            patch("galangal.ai.is_backend_available", return_value=True),
            patch("galangal.ai.get_backend_with_fallback", return_value=mock_backend),
            patch("galangal.core.artifacts.write_artifact"),
            patch("galangal.core.state.get_task_dir", return_value=tmp_path),
        ):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "REQUEST_CHANGES"

    def test_json_parsing_codex(self, tmp_path):
        """Codex (read-only) backend: JSON output parsed correctly."""
        engine = self._make_engine()
        tui_app = MagicMock()

        codex_output = json.dumps({
            "decision": "APPROVE",
            "review_notes": "## Summary\nAll criteria met.\n## Recommendation\nProceed.",
            "issues": [],
        })
        mock_result = StageResult.create_success("Done", output=codex_output)
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = mock_result
        mock_backend.read_only = True
        mock_backend.name = "codex"

        with (
            patch("galangal.ai.is_backend_available", return_value=True),
            patch("galangal.ai.get_backend_with_fallback", return_value=mock_backend),
            patch("galangal.core.artifacts.write_artifact"),
            patch("galangal.core.state.get_task_dir", return_value=tmp_path),
        ):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "APPROVE"
        assert "All criteria met" in notes

    def test_json_parsing_when_backend_not_read_only(self, tmp_path):
        """JSON peer review output is parsed even when backend is writable."""
        engine = self._make_engine()
        tui_app = MagicMock()

        output = json.dumps({
            "decision": "REQUEST_CHANGES",
            "review_notes": "Need better acceptance criteria coverage.",
            "issues": [],
        })
        mock_result = StageResult.create_success("Done", output=output)
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = mock_result
        mock_backend.read_only = False
        mock_backend.name = "codex"

        with (
            patch("galangal.ai.is_backend_available", return_value=True),
            patch("galangal.ai.get_backend_with_fallback", return_value=mock_backend),
            patch("galangal.core.artifacts.write_artifact"),
            patch("galangal.core.state.get_task_dir", return_value=tmp_path),
        ):
            decision, notes = engine.execute_peer_review(tui_app)

        assert decision == "REQUEST_CHANGES"
        assert "acceptance criteria" in notes


# =============================================================================
# Engine: _process_stage_result emits PEER_REVIEW_REQUIRED
# =============================================================================


class TestProcessStageResultPeerReview:
    def test_emits_peer_review_event(self):
        """Successful stage with peer review enabled emits PEER_REVIEW_REQUIRED."""
        state = make_state(stage=Stage.PM)
        config = GalangalConfig(
            peer_review=PeerReviewConfig(enabled=True, stages=["PM"]),
        )
        engine = WorkflowEngine(state, config)

        result = StageResult.create_success("PM complete")
        with patch("galangal.core.workflow.engine.artifact_exists", return_value=False):
            event = engine._process_stage_result(result)

        assert event.type == EventType.PEER_REVIEW_REQUIRED
        assert event.stage == Stage.PM

    def test_skips_peer_review_when_disabled(self):
        """Successful stage without peer review goes to normal flow."""
        state = make_state(stage=Stage.PM)
        config = GalangalConfig(
            peer_review=PeerReviewConfig(enabled=False),
        )
        engine = WorkflowEngine(state, config)

        result = StageResult.create_success("PM complete")
        with patch("galangal.core.workflow.engine.artifact_exists", return_value=False):
            event = engine._process_stage_result(result)

        # Should hit APPROVAL_REQUIRED since PM requires approval
        assert event.type == EventType.APPROVAL_REQUIRED


# =============================================================================
# Prompt building
# =============================================================================


class TestPeerReviewPromptBuilding:
    def test_pm_prompt_includes_artifacts(self, galangal_project, sample_task):
        """PM peer review prompt includes SPEC.md and PLAN.md."""
        # Create artifacts
        (sample_task / "SPEC.md").write_text("# Spec\nBuild a widget")
        (sample_task / "PLAN.md").write_text("# Plan\nStep 1: Build widget")

        with patch("galangal.config.loader.get_project_root", return_value=galangal_project):
            builder = PromptBuilder()
            state = make_state(task_description="Build a widget")
            prompt = builder.build_peer_review_prompt(state, Stage.PM, "codex")

        assert "Build a widget" in prompt
        assert "SPEC.md" in prompt or "Spec" in prompt

    def test_design_prompt_includes_spec_and_design(self, galangal_project, sample_task):
        """DESIGN peer review prompt includes SPEC.md and DESIGN.md."""
        (sample_task / "SPEC.md").write_text("# Spec\nBuild a widget")
        (sample_task / "DESIGN.md").write_text("# Design\nUse MVC pattern")

        with patch("galangal.config.loader.get_project_root", return_value=galangal_project):
            builder = PromptBuilder()
            state = make_state(stage=Stage.DESIGN, task_description="Build a widget")
            prompt = builder.build_peer_review_prompt(state, Stage.DESIGN, "codex")

        assert "Build a widget" in prompt
        assert "DESIGN.md" in prompt or "Design" in prompt

    def test_uses_backend_specific_prompt(self, galangal_project, sample_task):
        """Uses backend-specific prompt file when available (e.g., pm_peer_review_codex.md)."""
        with patch("galangal.config.loader.get_project_root", return_value=galangal_project):
            builder = PromptBuilder()
            state = make_state(task_description="Test task")
            prompt = builder.build_peer_review_prompt(state, Stage.PM, "codex")

        # Should use pm_peer_review_codex.md which has JSON format instructions
        assert "JSON" in prompt

    def test_falls_back_to_generic_prompt(self, galangal_project, sample_task):
        """Falls back to generic peer_review.md for unknown stages."""
        with patch("galangal.config.loader.get_project_root", return_value=galangal_project):
            builder = PromptBuilder()
            state = make_state(stage=Stage.DEV, task_description="Test task")
            prompt = builder.build_peer_review_prompt(state, Stage.DEV, "claude")

        # Should use the generic peer_review.md
        assert "DECISION" in prompt


# =============================================================================
# Auto-accept peer review
# =============================================================================


class TestPeerReviewAutoAccept:
    """Tests for auto-accept behavior in _handle_peer_review."""

    def _make_config(self, auto_accept=True, max_auto_loops=5):
        return GalangalConfig(
            peer_review=PeerReviewConfig(
                enabled=True,
                auto_accept=auto_accept,
                max_auto_loops=max_auto_loops,
            ),
        )

    @pytest.mark.asyncio
    async def test_auto_accept_rolls_back(self):
        """REQUEST_CHANGES with auto_accept=True triggers automatic rollback."""
        from galangal.core.workflow.tui_runner import _handle_peer_review

        config = self._make_config(auto_accept=True)
        state = make_state(stage=Stage.PM)
        engine = MagicMock()
        engine.state = state
        app = MagicMock()
        peer_review_loops: dict[str, int] = {}

        mock_to_thread = AsyncMock(
            return_value=("REQUEST_CHANGES", "Missing acceptance criteria")
        )

        with (
            patch("galangal.core.workflow.tui_runner.asyncio.to_thread", mock_to_thread),
            patch("galangal.core.workflow.tui_runner.save_state"),
            patch("galangal.core.artifacts.archive_artifact") as mock_archive,
        ):
            result = await _handle_peer_review(app, engine, config, peer_review_loops)

        assert result == "rollback"
        assert peer_review_loops["PM"] == 1
        assert state.last_failure is not None
        assert "Peer review feedback" in state.last_failure
        mock_archive.assert_called_once_with(
            "PM_PEER_REVIEW.md", "PM_PEER_REVIEW_PREV.md", state.task_name
        )

    @pytest.mark.asyncio
    async def test_auto_accept_increments_loop_counter(self):
        """Each auto-accept rollback increments the loop counter."""
        from galangal.core.workflow.tui_runner import _handle_peer_review

        config = self._make_config(auto_accept=True, max_auto_loops=5)
        state = make_state(stage=Stage.PM)
        engine = MagicMock()
        engine.state = state
        app = MagicMock()
        peer_review_loops: dict[str, int] = {"PM": 2}

        mock_to_thread = AsyncMock(return_value=("REQUEST_CHANGES", "Fix issues"))

        with (
            patch("galangal.core.workflow.tui_runner.asyncio.to_thread", mock_to_thread),
            patch("galangal.core.workflow.tui_runner.save_state"),
            patch("galangal.core.artifacts.archive_artifact"),
        ):
            result = await _handle_peer_review(app, engine, config, peer_review_loops)

        assert result == "rollback"
        assert peer_review_loops["PM"] == 3

    @pytest.mark.asyncio
    async def test_auto_accept_prompts_at_limit(self):
        """At max_auto_loops, falls through to manual prompt."""
        from galangal.core.workflow.tui_runner import _handle_peer_review

        config = self._make_config(auto_accept=True, max_auto_loops=3)
        state = make_state(stage=Stage.PM)
        engine = MagicMock()
        engine.state = state
        app = MagicMock()
        # Simulate user choosing to accept primary output
        app.prompt_async = AsyncMock(return_value="accept_primary")
        peer_review_loops: dict[str, int] = {"PM": 3}

        mock_to_thread = AsyncMock(return_value=("REQUEST_CHANGES", "Still has issues"))

        with (
            patch("galangal.core.workflow.tui_runner.asyncio.to_thread", mock_to_thread),
            patch("galangal.core.artifacts.read_artifact", return_value="spec content"),
            patch("galangal.core.workflow.tui_runner.save_state"),
        ):
            result = await _handle_peer_review(app, engine, config, peer_review_loops)

        assert result == "continue"
        # User was prompted (manual flow)
        app.prompt_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_manual_mode_always_prompts(self):
        """auto_accept=False always shows the comparison modal."""
        from galangal.core.workflow.tui_runner import _handle_peer_review

        config = self._make_config(auto_accept=False)
        state = make_state(stage=Stage.PM)
        engine = MagicMock()
        engine.state = state
        app = MagicMock()
        app.prompt_async = AsyncMock(return_value="accept_primary")
        peer_review_loops: dict[str, int] = {}

        mock_to_thread = AsyncMock(return_value=("REQUEST_CHANGES", "Needs work"))

        with (
            patch("galangal.core.workflow.tui_runner.asyncio.to_thread", mock_to_thread),
            patch("galangal.core.artifacts.read_artifact", return_value="spec"),
            patch("galangal.core.workflow.tui_runner.save_state"),
        ):
            result = await _handle_peer_review(app, engine, config, peer_review_loops)

        assert result == "continue"
        app.prompt_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_resets_loop_counter(self):
        """APPROVE decision resets the loop counter for that stage."""
        from galangal.core.workflow.tui_runner import _handle_peer_review

        config = self._make_config()
        state = make_state(stage=Stage.PM)
        engine = MagicMock()
        engine.state = state
        app = MagicMock()
        peer_review_loops: dict[str, int] = {"PM": 3}

        mock_to_thread = AsyncMock(return_value=("APPROVE", "Looks good!"))

        with patch("galangal.core.workflow.tui_runner.asyncio.to_thread", mock_to_thread):
            result = await _handle_peer_review(app, engine, config, peer_review_loops)

        assert result == "continue"
        assert "PM" not in peer_review_loops


# =============================================================================
# Archive artifact
# =============================================================================


class TestArchiveArtifact:
    """Tests for archive_artifact used during peer review rollback."""

    def test_archive_creates_new_file(self, tmp_path):
        """First archive creates the archive file with original content."""
        from galangal.core.artifacts import archive_artifact

        # Create the source artifact
        (tmp_path / "PM_PEER_REVIEW.md").write_text("# Review\nNeeds work")

        with patch("galangal.core.artifacts.artifact_path", side_effect=lambda name, tn=None: tmp_path / name):
            result = archive_artifact("PM_PEER_REVIEW.md", "PM_PEER_REVIEW_PREV.md")

        assert result is True
        assert not (tmp_path / "PM_PEER_REVIEW.md").exists()
        assert (tmp_path / "PM_PEER_REVIEW_PREV.md").read_text() == "# Review\nNeeds work"

    def test_archive_appends_with_separator(self, tmp_path):
        """Subsequent archives append with --- separator for multi-loop history."""
        from galangal.core.artifacts import archive_artifact

        # Create existing archive and new artifact
        (tmp_path / "PM_PEER_REVIEW_PREV.md").write_text("# Round 1\nFirst feedback")
        (tmp_path / "PM_PEER_REVIEW.md").write_text("# Round 2\nSecond feedback")

        with patch("galangal.core.artifacts.artifact_path", side_effect=lambda name, tn=None: tmp_path / name):
            result = archive_artifact("PM_PEER_REVIEW.md", "PM_PEER_REVIEW_PREV.md")

        assert result is True
        content = (tmp_path / "PM_PEER_REVIEW_PREV.md").read_text()
        assert "# Round 1\nFirst feedback" in content
        assert "\n\n---\n\n" in content
        assert "# Round 2\nSecond feedback" in content

    def test_archive_nonexistent_returns_false(self, tmp_path):
        """Returns False when source artifact doesn't exist."""
        from galangal.core.artifacts import archive_artifact

        with patch("galangal.core.artifacts.artifact_path", side_effect=lambda name, tn=None: tmp_path / name):
            result = archive_artifact("PM_PEER_REVIEW.md", "PM_PEER_REVIEW_PREV.md")

        assert result is False
