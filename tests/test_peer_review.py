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
from unittest.mock import MagicMock, patch

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
        """PeerReviewConfig is disabled by default."""
        config = PeerReviewConfig()
        assert config.enabled is False
        assert config.backend == "codex"
        assert config.stages == ["PM", "DESIGN"]

    def test_enabled_in_galangal_config(self):
        """peer_review field exists on GalangalConfig with defaults."""
        config = GalangalConfig()
        assert config.peer_review.enabled is False
        assert config.peer_review.backend == "codex"

    def test_custom_stages(self):
        """Can customize which stages get peer reviewed."""
        config = PeerReviewConfig(enabled=True, stages=["PM"])
        assert config.stages == ["PM"]


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
