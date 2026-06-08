"""Prompt prefix-stability / trailer-placement tests for build_full_prompt."""

from unittest.mock import patch

from galangal.core.state import Stage, TaskType, WorkflowState
from galangal.prompts.builder import MAX_ARTIFACT_BLOCK_CHARS, PromptBuilder


def _state(attempt=1, failure=None):
    return WorkflowState(
        task_name="t",
        stage=Stage.DEV,
        attempt=attempt,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=failure,
        started_at="2026-01-01T00:00:00+00:00",
        task_description="d",
        task_type=TaskType.FEATURE,
    )


def _build(state):
    # Avoid loading the embedding model in the mistake-warning path.
    with patch.object(PromptBuilder, "_get_mistake_warnings", return_value=""):
        return PromptBuilder().build_full_prompt(Stage.DEV, state)


def test_attempt_not_in_stable_prefix():
    prompt = _build(_state(attempt=1))
    assert "# Attempt" not in prompt
    assert "Previous Failure" not in prompt


def test_failure_trailer_at_end_attempt_one():
    # last_failure can be set with attempt==1 (after a guidance/staleness rollback).
    prompt = _build(_state(attempt=1, failure="use the cache layer"))
    assert "Previous Failure" in prompt
    assert prompt.rstrip().endswith("use the cache layer")


def test_attempt_and_emphasis_trailer_on_retry():
    prompt = _build(_state(attempt=3, failure="boom"))
    assert "# Attempt 3" in prompt
    assert "do not repeat it" in prompt
    # Volatile content comes after the stable prefix.
    assert prompt.index("# Attempt 3") > prompt.index("Current Stage")


def test_cap_artifact_block_trims_large_and_keeps_small():
    b = PromptBuilder()
    small = "# SMALL.md\ncontent"
    assert b._cap_artifact_block(small) == small
    big = "# BIG.md\n" + ("x" * (MAX_ARTIFACT_BLOCK_CHARS + 5000))
    capped = b._cap_artifact_block(big)
    assert len(capped) < len(big)
    assert "truncated to" in capped
