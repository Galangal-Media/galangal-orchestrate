"""Tests for the end-of-task cost/time report and related state."""

from datetime import datetime, timezone

from galangal.commands.complete import _fmt_duration, format_completion_report
from galangal.core.state import Stage, TaskType, WorkflowState


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


def test_fmt_duration():
    assert _fmt_duration(45) == "45s"
    assert _fmt_duration(125) == "2m 5s"
    assert _fmt_duration(3725) == "1h 2m"


def test_report_empty_when_no_data():
    assert format_completion_report(_state()) == ""


def test_report_includes_totals_and_per_stage():
    s = _state()
    s.stage = Stage.DEV
    s.add_usage({"cost_usd": 0.05, "input_tokens": 100, "output_tokens": 50})
    s.stage = Stage.REVIEW
    s.add_usage({"cost_usd": 0.03, "input_tokens": 10, "output_tokens": 5})
    s.stage_durations = {"DEV": 125, "REVIEW": 40}

    report = format_completion_report(s)

    assert "Cost: $0.0800" in report
    assert "Tokens: 165" in report
    assert "Active time: 2m 45s" in report
    # Per-stage lines, in pipeline order.
    assert "DEV: 2m 5s, $0.0500" in report
    assert "REVIEW: 40s, $0.0300" in report
    assert report.index("DEV:") < report.index("REVIEW:")


def test_report_shows_rollback_count():
    s = _state()
    s.add_usage({"cost_usd": 0.01})
    s.record_rollback(Stage.QA, Stage.DEV, "qa failed")
    assert "Rollbacks: 1" in format_completion_report(s)


def test_stage_costs_and_marker_round_trip():
    s = _state()
    s.stage = Stage.DEV
    s.add_usage({"cost_usd": 0.05})
    s.stage_in_progress = True

    restored = WorkflowState.from_dict(s.to_dict())
    assert restored.stage_costs == {"DEV": 0.05}
    assert restored.stage_in_progress is True
