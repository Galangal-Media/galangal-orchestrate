"""Tests for cumulative rollback-loop capping and opt-in per-stage model tiers."""

from galangal.ai import DEFAULT_STAGE_MODEL_TIERS, get_backend_for_stage
from galangal.config.schema import GalangalConfig
from galangal.core.state import (
    MAX_TOTAL_ROLLBACKS_PER_STAGE,
    RollbackEvent,
    Stage,
    TaskType,
    WorkflowState,
)


def _state():
    return WorkflowState(
        task_name="t",
        stage=Stage.QA,
        attempt=1,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at="2026-01-01T00:00:00+00:00",
        task_description="d",
        task_type=TaskType.FEATURE,
    )


class TestRollbackCumulativeCap:
    def test_slow_loop_blocked_by_total_cap(self):
        """Rollbacks outside the time window still count toward the total cap."""
        state = _state()
        for _ in range(MAX_TOTAL_ROLLBACKS_PER_STAGE):
            ev = RollbackEvent.create(Stage.QA, Stage.DEV, "loop")
            ev.timestamp = "2000-01-01T00:00:00+00:00"  # ancient -> outside window
            state._rollback.rollback_history.append(ev)

        assert state.get_rollback_count(Stage.DEV) == 0  # none recent
        assert state.get_total_rollback_count(Stage.DEV) == MAX_TOTAL_ROLLBACKS_PER_STAGE
        assert state.should_allow_rollback(Stage.DEV) is False

    def test_unrelated_stage_still_allowed(self):
        state = _state()
        for _ in range(MAX_TOTAL_ROLLBACKS_PER_STAGE):
            ev = RollbackEvent.create(Stage.QA, Stage.DEV, "loop")
            ev.timestamp = "2000-01-01T00:00:00+00:00"
            state._rollback.rollback_history.append(ev)
        assert state.should_allow_rollback(Stage.PM) is True

    def test_few_rollbacks_allowed(self):
        state = _state()
        state.record_rollback(Stage.QA, Stage.DEV, "once")
        assert state.should_allow_rollback(Stage.DEV) is True


class TestAutoModelTiers:
    def _config(self, **ai):
        base = {"default": "claude", "backends": {"claude": {"command": "claude", "args": []}}}
        base.update(ai)
        return GalangalConfig.model_validate({"ai": base})

    def setup_method(self):
        import galangal.ai as aimod

        self._orig = aimod.is_backend_available
        aimod.is_backend_available = lambda *a, **k: True

    def teardown_method(self):
        import galangal.ai as aimod

        aimod.is_backend_available = self._orig

    def test_mechanical_stage_gets_cheaper_model(self):
        cfg = self._config(auto_model_tiers=True)
        assert get_backend_for_stage(Stage.QA, cfg)._config.model == DEFAULT_STAGE_MODEL_TIERS["QA"]

    def test_reasoning_stage_keeps_cli_default(self):
        cfg = self._config(auto_model_tiers=True)
        assert get_backend_for_stage(Stage.DEV, cfg)._config.model is None

    def test_disabled_by_default(self):
        cfg = self._config()
        assert get_backend_for_stage(Stage.QA, cfg)._config.model is None

    def test_explicit_stage_model_overrides_tier(self):
        cfg = self._config(auto_model_tiers=True, stage_models={"QA": "opus"})
        assert get_backend_for_stage(Stage.QA, cfg)._config.model == "opus"
