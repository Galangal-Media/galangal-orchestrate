"""Deterministic, AI-free driver for the workflow engine.

Patches the single `_execute_stage` seam so the engine runs through real stage
advancement, rollback, fast-track, review-iteration, and skip logic with scripted
per-stage outcomes. This is the regression net for refactoring that resolver logic.
"""

from __future__ import annotations

import subprocess
from collections import deque
from unittest.mock import MagicMock, patch

import galangal.config.loader as loader
from galangal.config.defaults import generate_default_config
from galangal.core.state import Stage, TaskType, WorkflowState, save_state
from galangal.core.workflow.engine import ActionType, EventType, WorkflowEngine, action
from galangal.results import StageResult

# Outcome sentinels for a scripted stage result.
SUCCESS = "success"


def rollback(to: str, fast_track: bool = False):
    """Scripted outcome: roll back to `to` (stage value), optionally fast-track."""
    return ("rollback", to, fast_track)


def fail():
    """Scripted outcome: a generic stage failure (triggers retry / max-retries)."""
    return ("fail",)


class Policy:
    """Maps a stage to a queue of outcomes; defaults to SUCCESS when exhausted."""

    def __init__(self, outcomes: dict[str, list] | None = None):
        self._q = {k: deque(v) for k, v in (outcomes or {}).items()}

    def next_outcome(self, stage: Stage):
        q = self._q.get(stage.value)
        if q:
            return q.popleft()
        return SUCCESS


def init_project(tmp_path):
    """Initialize a temp project (git + config) and pin it as the project root."""
    (tmp_path / ".galangal").mkdir()
    # Inject commit_per_stage:false and a low retry cap INTO the existing stages
    # block (appending a second `stages:` key would clobber the skip list).
    cfg = generate_default_config("t").replace(
        "  max_retries: 5", "  max_retries: 2\n  commit_per_stage: false"
    )
    (tmp_path / ".galangal" / "config.yaml").write_text(cfg)
    # A git repo with no changes -> conditional stages (MIGRATION/CONTRACT/...) skip.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=tmp_path, check=True)
    loader.reset_caches()
    loader.set_project_root(tmp_path)


def simulate(
    tmp_path,
    policy: Policy | None = None,
    task_type: TaskType = TaskType.FEATURE,
    max_steps: int = 80,
) -> tuple[list[str], str]:
    """Run the engine to completion with scripted outcomes.

    Returns (trace, outcome) where trace is the ordered list of executed stage
    values and outcome is the terminal event name (WORKFLOW_COMPLETE, etc.).
    """
    init_project(tmp_path)
    policy = policy or Policy()

    state = WorkflowState.new("a task", "t", task_type)
    save_state(state)
    engine = WorkflowEngine(state)
    tui = MagicMock()
    trace: list[str] = []

    def fake_execute(st, tui_app=None, pause_check=None):
        outcome = policy.next_outcome(st.stage)
        if outcome == SUCCESS:
            return StageResult.create_success("ok")
        if outcome[0] == "rollback":
            return StageResult.rollback_required(
                "rollback", Stage.from_str(outcome[1]), is_fast_track=outcome[2]
            )
        return StageResult.error("boom")

    terminal = "MAX_STEPS"
    # Rollbacks log a "mistake", which would load the embedding model + run git;
    # that's not what we're exercising here, so stub it out for speed/quiet.
    with (
        patch("galangal.core.workflow.engine._execute_stage", side_effect=fake_execute),
        patch("galangal.mistakes.log_mistake"),
    ):
        while not engine.is_complete and len(trace) < max_steps:
            trace.append(engine.state.stage.value)
            ev = engine.execute_current_stage(tui)
            t = ev.type

            if t == EventType.APPROVAL_REQUIRED:
                engine.handle_action(action(ActionType.APPROVE, approver="t"), tui_app=tui)
                t = EventType.STAGE_COMPLETED  # fall through to advance

            if t == EventType.STAGE_COMPLETED:
                adv = engine.handle_action(action(ActionType.CONTINUE), tui_app=tui)
                if adv.type == EventType.WORKFLOW_COMPLETE or engine.is_complete:
                    terminal = "WORKFLOW_COMPLETE"
                    break
            elif t == EventType.ROLLBACK_TRIGGERED:
                continue  # handle_rollback already set state.stage to the target
            elif t == EventType.STAGE_FAILED:
                continue  # retry the same stage
            else:
                terminal = t.name
                break

    return trace, terminal
