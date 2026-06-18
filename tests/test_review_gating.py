"""Tests for severity-gated REVIEW auto-approve, recurring-issue tracking,
the autonomous arbiter, and content-hash stage caching."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from galangal.config.schema import GalangalConfig, ProjectConfig, StageConfig
from galangal.core.artifacts import read_artifact
from galangal.core.state import Stage, review_issue_fingerprint, review_severity_rank
from galangal.core.workflow.core import _write_schema_artifacts, handle_rollback
from galangal.core.workflow.engine import ActionType, WorkflowEngine, action
from galangal.results import StageResult
from galangal.validation.runner import ValidationRunner
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

    def test_files_reviewed_written_to_notes(self, sample_task: Path):
        ui = MockStageUI()
        state = make_state(stage=Stage.REVIEW)
        data = {
            "review_notes": "notes",
            "decision": "APPROVE",
            "issues": [],
            "files_reviewed": [
                {"file": "a.py", "verdict": "clean"},
                {"file": "b.py", "verdict": "fixed null check"},
            ],
        }
        with patch("galangal.core.workflow.core.get_config", return_value=_cfg("major")):
            with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                with patch("galangal.core.workflow.core.save_state"):
                    _write_schema_artifacts(
                        data, REVIEW_SCHEMA, Stage.REVIEW, "test-task", ui, state
                    )
        notes = read_artifact("REVIEW_NOTES.md", "test-task") or ""
        assert "Files Reviewed" in notes
        assert "a.py" in notes and "b.py" in notes


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

    def test_recurring_issues_logged_to_mistake_db(self, sample_task: Path):
        state = make_state(task_name="test-task", stage=Stage.REVIEW)
        state.record_review_issue_round([_issue("major", desc="leak")])
        state.record_review_issue_round([_issue("major", desc="leak again")])
        result = StageResult.rollback_required(message="changes", rollback_to=Stage.DEV)
        with patch("galangal.core.workflow.core.get_task_dir", return_value=sample_task):
            with patch("galangal.core.artifacts.get_task_dir", return_value=sample_task):
                with patch("galangal.core.workflow.core.save_state"):
                    with patch("galangal.mistakes.log_mistake") as mock_log:
                        handle_rollback(state, result)
        assert mock_log.called
        assert any("Recurring REVIEW issue" in c.args[0] for c in mock_log.call_args_list)


class TestArbiter:
    def _engine(self, enabled=True, after=2, stage=Stage.REVIEW):
        state = make_state(stage=stage)
        config = GalangalConfig(
            stages=StageConfig(arbiter_enabled=enabled, arbiter_after_rounds=after)
        )
        return WorkflowEngine(state, config), state

    def _result(self):
        return StageResult.rollback_required(message="changes", rollback_to=Stage.DEV)

    def _two_rounds(self, state):
        state.record_review_issue_round([_issue("major", desc="x")])
        state.record_review_issue_round([_issue("major", desc="x reworded")])

    def test_disabled_is_na(self):
        engine, state = self._engine(enabled=False)
        self._two_rounds(state)
        assert engine._maybe_arbitrate_review(self._result()) == "n/a"

    def test_below_threshold_is_na(self):
        engine, state = self._engine(after=3)  # times_seen will be 2 < 3
        self._two_rounds(state)
        assert engine._maybe_arbitrate_review(self._result()) == "n/a"

    def test_non_review_stage_is_na(self):
        engine, state = self._engine(stage=Stage.QA)
        self._two_rounds(state)
        assert engine._maybe_arbitrate_review(self._result()) == "n/a"

    def _run(self, engine, verdict, tmp_path):
        backend = MagicMock()
        backend.generate_text.return_value = json.dumps(
            {"verdict": verdict, "reasoning": "because reasons"}
        )
        writes: dict[str, str] = {}
        with (
            patch("galangal.ai.get_backend_with_fallback", return_value=backend),
            patch("galangal.core.workflow.engine.read_artifact", return_value=""),
            patch(
                "galangal.core.workflow.engine.write_artifact",
                side_effect=lambda name, content, task: writes.__setitem__(name, content),
            ),
        ):
            result = engine._maybe_arbitrate_review(self._result())
        return result, writes

    def test_overturn_writes_approve_decision(self, tmp_path):
        engine, state = self._engine(after=2)
        self._two_rounds(state)
        verdict, writes = self._run(engine, "overturn", tmp_path)
        assert verdict == "overturn"
        assert writes.get("REVIEW_DECISION") == "APPROVE"
        assert "Arbiter override" in writes.get("REVIEW_NOTES.md", "")

    def test_uphold_does_not_approve(self, tmp_path):
        engine, state = self._engine(after=2)
        self._two_rounds(state)
        verdict, writes = self._run(engine, "uphold", tmp_path)
        assert verdict == "uphold"
        assert "REVIEW_DECISION" not in writes
        assert "UPHELD" in writes.get("REVIEW_NOTES.md", "")

    def test_unparseable_fails_safe_to_uphold(self, tmp_path):
        engine, state = self._engine(after=2)
        self._two_rounds(state)
        backend = MagicMock()
        backend.generate_text.return_value = "not json at all"
        with (
            patch("galangal.ai.get_backend_with_fallback", return_value=backend),
            patch("galangal.core.workflow.engine.read_artifact", return_value=""),
            patch("galangal.core.workflow.engine.write_artifact"),
        ):
            assert engine._maybe_arbitrate_review(self._result()) == "uphold"


class TestFixInDevResetsCaps:
    def test_fix_in_dev_resets_review_iteration_count(self, tmp_path):
        state = make_state(stage=Stage.REVIEW)
        state.review_iteration_count = 10  # cap hit
        engine = WorkflowEngine(state, GalangalConfig())
        with patch("galangal.core.workflow.engine.save_state"):
            engine.handle_action(action(ActionType.FIX_IN_DEV, error="changes"))
        assert state.stage == Stage.DEV
        assert state.review_iteration_count == 0  # fresh budget for another loop


class TestStageInputCaching:
    def _runner_with_inputs(self, globs):
        runner = ValidationRunner()
        runner.config = GalangalConfig.model_validate(
            {"validation": {"qa": {"inputs": globs}}}
        )
        return runner

    def test_no_inputs_is_not_cacheable(self, galangal_project: Path):
        runner = ValidationRunner()  # default config, no inputs
        assert runner.compute_stage_input_hash("QA") is None

    def test_hash_is_content_sensitive(self, galangal_project: Path, monkeypatch):
        runner = self._runner_with_inputs(["*.py"])
        (galangal_project / "a.py").write_text("print(1)")
        monkeypatch.setattr(runner, "_get_all_changed_files", lambda: {"a.py"})
        h1 = runner.compute_stage_input_hash("QA")
        assert h1 is not None

        (galangal_project / "a.py").write_text("print(2)")
        h2 = runner.compute_stage_input_hash("QA")
        assert h1 != h2  # content changed -> hash changed

        (galangal_project / "a.py").write_text("print(1)")
        assert runner.compute_stage_input_hash("QA") == h1  # back to original

    def test_non_matching_change_keeps_hash_stable(self, galangal_project: Path, monkeypatch):
        runner = self._runner_with_inputs(["src/**/*.py"])
        (galangal_project / "a.py").write_text("x")  # not under src/
        changed = {"a.py"}
        monkeypatch.setattr(runner, "_get_all_changed_files", lambda: set(changed))
        h1 = runner.compute_stage_input_hash("QA")
        changed.add("README.md")  # still nothing matching src/**/*.py
        assert runner.compute_stage_input_hash("QA") == h1
