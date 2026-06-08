"""End-to-end engine simulations via the AI-free harness.

These exercise the real stage resolver (get_next_stage), rollback handling,
fast-track / review-iteration, REDESIGN routing, and task-type skips. They are the
regression net for refactoring that logic.
"""

from galangal.core.state import TaskType
from tests.workflow_harness import Policy, rollback, simulate


def test_feature_happy_path(tmp_path):
    trace, terminal = simulate(tmp_path)
    assert terminal == "WORKFLOW_COMPLETE"
    # Conditional/disabled stages (MIGRATION, TEST_GATE, CONTRACT, BENCHMARK) skip.
    assert trace == [
        "PM", "DESIGN", "PREFLIGHT", "DEV", "TEST", "QA", "SECURITY",
        "REVIEW", "DOCS", "SUMMARY",
    ]


def test_review_request_changes_loops_dev_review_then_full_pipeline(tmp_path):
    # REVIEW asks for changes once: DEV->REVIEW loop (intermediate stages skipped),
    # then on APPROVE the full validation pipeline re-runs before final REVIEW.
    trace, terminal = simulate(tmp_path, Policy({"REVIEW": [rollback("DEV")]}))
    assert terminal == "WORKFLOW_COMPLETE"
    # The iteration loop: REVIEW -> DEV -> REVIEW with no intermediate stages.
    i = trace.index("REVIEW")
    assert trace[i:i + 3] == ["REVIEW", "DEV", "REVIEW"]
    # After re-approval, QA/SECURITY run again before the final REVIEW.
    assert trace.count("QA") == 2
    assert trace.count("REVIEW") == 3


def test_redesign_rolls_back_to_design(tmp_path):
    # REVIEW returns REDESIGN -> rolls back to DESIGN and re-runs from there.
    trace, terminal = simulate(tmp_path, Policy({"REVIEW": [rollback("DESIGN")]}))
    assert terminal == "WORKFLOW_COMPLETE"
    first_review = trace.index("REVIEW")
    assert trace[first_review + 1] == "DESIGN"  # rolled back to DESIGN, not DEV
    assert trace.count("DESIGN") == 2


def test_qa_failure_rolls_back_to_dev(tmp_path):
    trace, terminal = simulate(tmp_path, Policy({"QA": [rollback("DEV")]}))
    assert terminal == "WORKFLOW_COMPLETE"
    qa = trace.index("QA")
    assert trace[qa + 1] == "DEV"  # QA failure goes back to DEV
    assert trace.count("DEV") == 2


def test_hotfix_fast_path(tmp_path):
    trace, terminal = simulate(tmp_path, task_type=TaskType.HOTFIX)
    assert terminal == "WORKFLOW_COMPLETE"
    assert trace == ["PM", "DEV", "TEST", "SUMMARY"]


def test_docs_task_minimal_path(tmp_path):
    trace, terminal = simulate(tmp_path, task_type=TaskType.DOCS)
    assert terminal == "WORKFLOW_COMPLETE"
    assert "DEV" not in trace and "REVIEW" not in trace
    assert "DOCS" in trace


def test_qa_repeated_rollback_eventually_blocks(tmp_path):
    # QA->DEV is a normal (non-exempt) rollback edge: repeated failures hit the
    # per-stage rollback cap and the engine blocks rather than looping forever.
    trace, terminal = simulate(
        tmp_path, Policy({"QA": [rollback("DEV")] * 20}), max_steps=120
    )
    assert terminal == "ROLLBACK_BLOCKED"


def test_review_dev_loop_is_exempt_from_rollback_cap(tmp_path):
    # The DEV<->REVIEW iteration is deliberately exempt from the cap (the user
    # check-in is the interactive escape hatch). Many REQUEST_CHANGES rounds then
    # an approval should complete, not block.
    trace, terminal = simulate(
        tmp_path, Policy({"REVIEW": [rollback("DEV")] * 8}), max_steps=200
    )
    assert terminal == "WORKFLOW_COMPLETE"
    assert trace.count("DEV") >= 8
