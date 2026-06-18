"""Tests for severity-gated REVIEW auto-approve and recurring-issue tracking."""

from pathlib import Path
from unittest.mock import patch

from galangal.config.schema import GalangalConfig, ProjectConfig, StageConfig
from galangal.core.artifacts import read_artifact
from galangal.core.state import Stage, review_issue_fingerprint, review_severity_rank
from galangal.core.workflow.core import _write_schema_artifacts, handle_rollback
from galangal.results import StageResult
from tests.conftest import MockStageUI, make_state

REVIEW_SCHEMA = {
    "notes_file": "REVIEW_NOTES.md",
    "notes_field": "review_notes",
    "decision_file": "REVIEW_DECISION",
    "decision_field": "decision",
    "issues_field": "issues",
}


def _cfg(severity: str = "major") -> GalangalConfig:
    return GalangalConfig(
        project=ProjectConfig(name="t"),
        stages=StageConfig(review_block_min_severity=severity),
    )


def _issue(severity, file="a.py", line=10, desc="bug"):
    return {"severity": severity, "file": file, "line": line, "description": desc}


class TestSeverityHelpers:
    def test_rank_ordering(self):
        assert (
            review_severity_rank("suggestion")
            < review_severity_rank("minor")
            < review_severity_rank("major")
            < review_severity_rank("critical")
        )

    def test_unknown_severity_ranks_highest(self):
        # An unrecognised label must never silently bypass a block.
        assert review_severity_rank("weird") == review_severity_rank("critical")
        assert review_severity_rank(None) == review_severity_rank("critical")

    def test_fingerprint_keys_on_file_line(self):
        # Same file:line, different wording -> same fingerprint.
        a = review_issue_fingerprint(_issue("major", desc="bug here"))
        b = review_issue_fingerprint(_issue("minor", desc="totally different words"))
        assert a == b


class TestRecurringIssueTracking:
    def test_recurrence_detected_across_rounds(self):
        state = make_state(stage=Stage.REVIEW)
        state.record_review_issue_round([_issue("major", desc="first wording")])
        state.record_review_issue_round(
            [_issue("major", desc="reworded"), _issue("minor", file="b.py", line=2, desc="new")]
        )
        recurring = state.recurring_review_issues()
        assert len(recurring) == 1
        assert recurring[0]["file"] == "a.py"
        assert recurring[0]["times_seen"] == 2

    def test_no_recurrence_on_first_round(self):
        state = make_state(stage=Stage.REVIEW)
        state.record_review_issue_round([_issue("major")])
        assert state.recurring_review_issues() == []

    def test_reset_on_review_iteration_complete(self):
        state = make_state(stage=Stage.REVIEW)
        state.record_review_issue_round([_issue("major")])
        state.complete_review_iteration()
        assert state.review_issue_rounds == []

    def test_rounds_survive_serialization(self):
        state = make_state(stage=Stage.REVIEW)
        state.record_review_issue_round([_issue("major")])
        state.record_review_issue_round([_issue("major", desc="again")])
        restored = type(state).from_dict(state.to_dict())
        assert restored.review_issue_rounds == state.review_issue_rounds
        assert len(restored.recurring_review_issues()) == 1


class TestSeverityGatedAutoApprove:
    def _run(self, sample_task: Path, decision, issues, severity="major"):
        ui = MockStageUI()
        state = make_state(stage=Stage.REVIEW)
        data = {"review_notes": "notes", "decision": decision, "issues": issues}
        with patch("galangal.core.workflow.core.get_config", return_value=_cfg(severity)):
            with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                with patch("galangal.core.workflow.core.save_state"):
                    _write_schema_artifacts(data, REVIEW_SCHEMA, Stage.REVIEW, "test-task", ui, state)
        return state, (read_artifact("REVIEW_DECISION", "test-task") or "").strip()

    def test_only_minor_issues_auto_approves(self, sample_task: Path):
        state, decision = self._run(
            sample_task, "REQUEST_CHANGES", [_issue("minor"), _issue("suggestion", file="b.py", line=1)]
        )
        assert decision == "APPROVE"
        # Auto-approved round is not recorded as a blocking round.
        assert state.review_issue_rounds == []

    def test_a_major_issue_still_blocks(self, sample_task: Path):
        state, decision = self._run(
            sample_task, "REQUEST_CHANGES", [_issue("minor"), _issue("major", file="c.py", line=9)]
        )
        assert decision == "REQUEST_CHANGES"
        assert len(state.review_issue_rounds) == 1

    def test_lower_threshold_blocks_on_minor(self, sample_task: Path):
        # threshold=minor -> a minor issue is blocking, no auto-approve.
        _, decision = self._run(sample_task, "REQUEST_CHANGES", [_issue("minor")], severity="minor")
        assert decision == "REQUEST_CHANGES"

    def test_approve_passes_through_untouched(self, sample_task: Path):
        _, decision = self._run(sample_task, "APPROVE", [])
        assert decision == "APPROVE"


class TestRollbackSurfacesRecurringIssues:
    def test_recurring_section_in_rollback_md(self, sample_task: Path):
        state = make_state(task_name="test-task", stage=Stage.REVIEW)
        state.record_review_issue_round([_issue("major", desc="leak")])
        state.record_review_issue_round([_issue("major", desc="leak still there")])

        result = StageResult.rollback_required(message="Review requested changes", rollback_to=Stage.DEV)
        with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
            with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                with patch("galangal.core.workflow.core.save_state"):
                    handled = handle_rollback(state, result)

        assert handled is True
        content = read_artifact("ROLLBACK.md", "test-task") or ""
        assert "RECURRING ISSUES" in content
        assert "raised 2x" in content
