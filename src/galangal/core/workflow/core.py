"""
Core workflow utilities - stage execution, rollback handling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from galangal.ai.base import PauseCheck
from galangal.ai.claude import ClaudeBackend
from galangal.config.loader import get_config
from galangal.core.artifacts import artifact_exists, artifact_path, read_artifact, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    Stage,
    WorkflowState,
    get_task_dir,
    save_state,
    should_skip_for_task_type,
)
from galangal.prompts.builder import PromptBuilder
from galangal.results import StageResult, StageResultType
from galangal.ui.tui import TUIAdapter
from galangal.validation.runner import ValidationRunner

if TYPE_CHECKING:
    from galangal.ui.tui import WorkflowTUIApp


def get_next_stage(
    current: Stage, state: WorkflowState
) -> Stage | None:
    """Get the next stage, handling conditional stages and task type skipping."""
    config = get_config()
    task_name = state.task_name
    task_type = state.task_type
    idx = STAGE_ORDER.index(current)

    if idx >= len(STAGE_ORDER) - 1:
        return None

    next_stage = STAGE_ORDER[idx + 1]

    # Check config-level skipping
    if next_stage.value in [s.upper() for s in config.stages.skip]:
        return get_next_stage(next_stage, state)

    # Check task type skipping
    if should_skip_for_task_type(next_stage, task_type):
        return get_next_stage(next_stage, state)

    # Check conditional stages via validation runner
    runner = ValidationRunner()
    if next_stage == Stage.MIGRATION:
        if artifact_exists("MIGRATION_SKIP.md", task_name):
            return get_next_stage(next_stage, state)
        # Check skip condition
        result = runner.validate_stage("MIGRATION", task_name)
        if result.message.endswith("(condition met)"):
            return get_next_stage(next_stage, state)

    elif next_stage == Stage.CONTRACT:
        if artifact_exists("CONTRACT_SKIP.md", task_name):
            return get_next_stage(next_stage, state)
        result = runner.validate_stage("CONTRACT", task_name)
        if result.message.endswith("(condition met)"):
            return get_next_stage(next_stage, state)

    elif next_stage == Stage.BENCHMARK:
        if artifact_exists("BENCHMARK_SKIP.md", task_name):
            return get_next_stage(next_stage, state)
        result = runner.validate_stage("BENCHMARK", task_name)
        if result.message.endswith("(condition met)"):
            return get_next_stage(next_stage, state)

    return next_stage


def execute_stage(
    state: WorkflowState,
    tui_app: WorkflowTUIApp,
    pause_check: PauseCheck | None = None,
) -> StageResult:
    """Execute the current stage. Returns structured StageResult.

    Args:
        state: Current workflow state
        tui_app: TUI application for UI feedback
        pause_check: Optional callback that returns True if pause requested
    """
    stage = state.stage
    task_name = state.task_name

    if stage == Stage.COMPLETE:
        return StageResult.success("Workflow complete")

    # Check for clarification
    if artifact_exists("QUESTIONS.md", task_name) and not artifact_exists(
        "ANSWERS.md", task_name
    ):
        state.clarification_required = True
        save_state(state)
        return StageResult.clarification_needed()

    # PREFLIGHT runs validation directly
    if stage == Stage.PREFLIGHT:
        tui_app.add_activity("Running preflight checks...", "⚙")

        runner = ValidationRunner()
        result = runner.validate_stage("PREFLIGHT", task_name)

        if result.success:
            tui_app.show_message(f"Preflight: {result.message}", "success")
            return StageResult.success(result.message)
        else:
            return StageResult.preflight_failed(
                message=result.message,
                details=result.output or "",
            )

    # Build prompt
    builder = PromptBuilder()
    prompt = builder.build_full_prompt(stage, state)

    # Add retry context
    if state.attempt > 1 and state.last_failure:
        retry_context = f"""
## ⚠️ RETRY ATTEMPT {state.attempt}

The previous attempt failed with the following error:

```
{state.last_failure[:1000]}
```

Please fix the issue above before proceeding. Do not repeat the same mistake.
"""
        prompt = f"{prompt}\n\n{retry_context}"

    # Log the prompt
    logs_dir = get_task_dir(task_name) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{stage.value.lower()}_{state.attempt}.log"
    with open(log_file, "w") as f:
        f.write(f"=== Prompt ===\n{prompt}\n\n")

    # Run stage with TUI
    backend = ClaudeBackend()
    ui = TUIAdapter(tui_app)
    invoke_result = backend.invoke(
        prompt=prompt,
        timeout=14400,
        max_turns=200,
        ui=ui,
        pause_check=pause_check,
    )

    # Log the output
    with open(log_file, "a") as f:
        f.write(f"=== Output ===\n{invoke_result.output or invoke_result.message}\n")

    # Return early if AI invocation failed
    if not invoke_result.success:
        return invoke_result

    # Validate stage
    tui_app.add_activity("Validating stage outputs...", "⚙")

    runner = ValidationRunner()
    result = runner.validate_stage(stage.value, task_name)

    with open(log_file, "a") as f:
        f.write(f"\n=== Validation ===\n{result.message}\n")

    if result.success:
        tui_app.show_message(result.message, "success")
        return StageResult.success(result.message, output=invoke_result.output)
    else:
        tui_app.show_message(result.message, "error")
        # Check if rollback is required
        if result.rollback_to:
            return StageResult.rollback_required(
                message=result.message,
                rollback_to=Stage.from_str(result.rollback_to),
                output=invoke_result.output,
            )
        return StageResult.validation_failed(result.message)


def archive_rollback_if_exists(task_name: str, tui_app: WorkflowTUIApp) -> None:
    """Archive ROLLBACK.md after DEV stage succeeds."""
    if not artifact_exists("ROLLBACK.md", task_name):
        return

    rollback_content = read_artifact("ROLLBACK.md", task_name)
    resolved_path = artifact_path("ROLLBACK_RESOLVED.md", task_name)

    resolution_note = f"\n\n## Resolved: {datetime.now(timezone.utc).isoformat()}\n\nIssues fixed by DEV stage.\n"

    if resolved_path.exists():
        existing = resolved_path.read_text()
        resolved_path.write_text(
            existing + "\n---\n" + rollback_content + resolution_note
        )
    else:
        resolved_path.write_text(rollback_content + resolution_note)

    rollback_path = artifact_path("ROLLBACK.md", task_name)
    rollback_path.unlink()

    tui_app.add_activity("Archived ROLLBACK.md → ROLLBACK_RESOLVED.md", "📋")


def handle_rollback(state: WorkflowState, result: StageResult) -> bool:
    """Handle a rollback from a StageResult.

    Updates state and writes to ROLLBACK.md. The caller is responsible
    for showing any UI feedback.

    Args:
        state: Current workflow state
        result: StageResult with type=ROLLBACK_REQUIRED and rollback_to set

    Returns:
        True if rollback was handled, False if result wasn't a rollback
    """
    if result.type != StageResultType.ROLLBACK_REQUIRED or result.rollback_to is None:
        return False

    task_name = state.task_name
    from_stage = state.stage
    target_stage = result.rollback_to
    reason = result.message

    rollback_entry = f"""
## Rollback from {from_stage.value}

**Date:** {datetime.now(timezone.utc).isoformat()}
**From Stage:** {from_stage.value}
**Target Stage:** {target_stage.value}
**Reason:** {reason}

### Required Actions
{reason}

---
"""

    existing = read_artifact("ROLLBACK.md", task_name)
    if existing:
        new_content = existing + rollback_entry
    else:
        new_content = f"# Rollback Log\n\nThis file tracks issues that required rolling back to earlier stages.\n{rollback_entry}"

    write_artifact("ROLLBACK.md", new_content, task_name)

    state.stage = target_stage
    state.attempt = 1
    state.last_failure = f"Rollback from {from_stage.value}: {reason}"
    save_state(state)

    return True
