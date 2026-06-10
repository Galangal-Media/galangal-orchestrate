"""Tests for the task cost circuit breaker (engine._check_budget)."""

from datetime import datetime, timezone

from galangal.config.schema import GalangalConfig, StageConfig
from galangal.core.state import Stage, TaskType, WorkflowState
from galangal.core.workflow.engine import EventType, WorkflowEngine


def _state() -> WorkflowState:
    return WorkflowState(
        task_name="t",
        stage=Stage.DEV,
        attempt=1,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        task_description="d",
        task_type=TaskType.FEATURE,
    )


def _engine(max_cost=0.0, max_tokens=0) -> WorkflowEngine:
    config = GalangalConfig(
        stages=StageConfig(max_task_cost_usd=max_cost, max_task_tokens=max_tokens)
    )
    return WorkflowEngine(_state(), config)


def test_no_breaker_when_disabled():
    engine = _engine(max_cost=0.0)
    engine.state.task_cost_usd = 999.0
    assert engine._check_budget() is None


def test_breaker_fires_over_cost():
    engine = _engine(max_cost=1.0)
    engine.state.task_cost_usd = 1.5
    evt = engine._check_budget()
    assert evt is not None
    assert evt.type == EventType.BUDGET_EXCEEDED
    assert evt.data["cost_usd"] == 1.5


def test_breaker_fires_over_tokens():
    engine = _engine(max_tokens=1000)
    engine.state.task_tokens = 1500
    evt = engine._check_budget()
    assert evt is not None and evt.type == EventType.BUDGET_EXCEEDED


def test_under_budget_passes():
    engine = _engine(max_cost=5.0)
    engine.state.task_cost_usd = 1.0
    assert engine._check_budget() is None


def test_ack_suppresses_breaker():
    engine = _engine(max_cost=1.0)
    engine.state.task_cost_usd = 99.0
    engine.state.budget_ack = True
    assert engine._check_budget() is None
