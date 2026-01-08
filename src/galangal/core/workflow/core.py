"""
Core workflow utilities - stage execution, rollback handling.
"""

from __future__ import annotations

import time
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
    get_conditional_stages,
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


# Get conditional stages from metadata (cached at module load)
CONDITIONAL_STAGES: dict[Stage, str] = get_conditional_stages()


def _should_skip_conditional_stage(
    stage: Stage, task_name: str, runner: ValidationRunner
) -> bool:
    """
    Check if a conditional stage should be skipped.

    Conditional stages (MIGRATION, CONTRACT, BENCHMARK) can be skipped if:
    1. A manual skip artifact exists (e.g., MIGRATION_SKIP.md)
    2. The validation runner's skip_if condition is met (e.g., no matching files)

    Args:
        stage: The stage to check.
        task_name: Name of the task for artifact lookup.
        runner: ValidationRunner instance for checking skip conditions.

    Returns:
        True if the stage should be skipped, False otherwise.
    """
    if stage not in CONDITIONAL_STAGES:
        return False

    skip_artifact = CONDITIONAL_STAGES[stage]

    # Check for manual skip artifact
    if artifact_exists(skip_artifact, task_name):
        return True

    # Check validation skip condition
    result = runner.validate_stage(stage.value.upper(), task_name)
    return result.skipped


def get_next_stage(
    current: Stage, state: WorkflowState
) -> Stage | None:
    """
    Determine the next stage in the workflow pipeline.

    Walks the STAGE_ORDER list starting from the current stage, skipping
    stages that should be bypassed based on:
    1. Config-level skipping (config.stages.skip)
    2. Task type skipping (e.g., DOCS tasks skip TEST, BENCHMARK)
    3. Conditional stages with skip_if conditions (MIGRATION, CONTRACT, BENCHMARK)
    4. Manual skip artifacts (e.g., MIGRATION_SKIP.md)

    This function is recursive - if the next stage should be skipped, it
    calls itself to find the next non-skipped stage.

    Args:
        current: The stage that just completed.
        state: Current workflow state containing task_name and task_type.

    Returns:
        The next stage to execute, or None if current is the last stage.
    """
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

    # Check conditional stages (MIGRATION, CONTRACT, BENCHMARK)
    if next_stage in CONDITIONAL_STAGES:
        runner = ValidationRunner()
        if _should_skip_conditional_stage(next_stage, task_name, runner):
            return get_next_stage(next_stage, state)

    return next_stage


def execute_stage(
    state: WorkflowState,
    tui_app: WorkflowTUIApp,
    pause_check: PauseCheck | None = None,
) -> StageResult:
    """
    Execute a single workflow stage and validate its output.

    This function handles the full lifecycle of a stage execution:
    1. Check for pending clarifications (QUESTIONS.md without ANSWERS.md)
    2. For PREFLIGHT stage: run validation checks directly
    3. For other stages: build prompt, invoke AI backend, validate output

    The prompt is built using PromptBuilder which merges default prompts
    with project-specific overrides. Retry context is appended when
    state.attempt > 1.

    All prompts and outputs are logged to the task's logs/ directory.

    Args:
        state: Current workflow state containing stage, task_name, attempt count,
            and last_failure for retry context.
        tui_app: TUI application instance for displaying progress and messages.
        pause_check: Optional callback that returns True if a pause was requested
            (e.g., user pressed Ctrl+C). Passed to ClaudeBackend for graceful stop.

    Returns:
        StageResult with one of:
        - SUCCESS: Stage completed and validated successfully
        - PREFLIGHT_FAILED: Preflight checks failed
        - VALIDATION_FAILED: Stage output failed validation
        - ROLLBACK_REQUIRED: Validation indicated rollback needed
        - CLARIFICATION_NEEDED: Questions pending without answers
        - PAUSED/TIMEOUT/ERROR: AI execution issues
    """
    from galangal.logging import workflow_logger

    stage = state.stage
    task_name = state.task_name
    config = get_config()
    start_time = time.time()

    # Log stage start
    workflow_logger.stage_started(
        stage=stage.value,
        task_name=task_name,
        attempt=state.attempt,
        max_retries=config.stages.max_retries,
    )

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

    duration = time.time() - start_time

    # Log validation result
    workflow_logger.validation_result(
        stage=stage.value,
        task_name=task_name,
        success=result.success,
        message=result.message,
        skipped=result.skipped,
    )

    if result.success:
        tui_app.show_message(result.message, "success")
        workflow_logger.stage_completed(
            stage=stage.value,
            task_name=task_name,
            success=True,
            duration=duration,
        )
        return StageResult.success(result.message, output=invoke_result.output)
    else:
        tui_app.show_message(result.message, "error")
        workflow_logger.stage_failed(
            stage=stage.value,
            task_name=task_name,
            error=result.message,
            attempt=state.attempt,
        )
        # Check if rollback is required
        if result.rollback_to:
            return StageResult.rollback_required(
                message=result.message,
                rollback_to=Stage.from_str(result.rollback_to),
                output=invoke_result.output,
            )
        return StageResult.validation_failed(result.message)


def archive_rollback_if_exists(task_name: str, tui_app: WorkflowTUIApp) -> None:
    """
    Archive ROLLBACK.md to ROLLBACK_RESOLVED.md after DEV stage succeeds.

    When validation failures or manual review trigger a rollback to DEV,
    the issues are recorded in ROLLBACK.md. Once DEV completes successfully,
    this function moves the rollback content to ROLLBACK_RESOLVED.md with
    a resolution timestamp.

    Multiple rollbacks are accumulated in ROLLBACK_RESOLVED.md, separated
    by horizontal rules, providing a history of issues encountered.

    Args:
        task_name: Name of the task to archive rollback for.
        tui_app: TUI app for displaying archive notification.
    """
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
    """
    Process a rollback from validation failure.

    When validation indicates a rollback is needed (e.g., QA fails and needs
    to go back to DEV), this function:
    1. Checks if rollback is allowed (prevents infinite loops)
    2. Records the rollback in state history
    3. Appends the rollback details to ROLLBACK.md
    4. Updates the workflow state to target stage
    5. Resets attempt counter and records failure reason

    The ROLLBACK.md file serves as context for the target stage, describing
    what issues need to be fixed.

    Rollback loop prevention: If too many rollbacks to the same stage occur
    within the time window (default: 3 within 1 hour), the rollback is blocked
    and returns False.

    Args:
        state: Current workflow state to update. Modified in place.
        result: StageResult with type=ROLLBACK_REQUIRED and rollback_to set.
            The message field describes what needs to be fixed.

    Returns:
        True if rollback was processed (result was ROLLBACK_REQUIRED type).
        False if result was not a rollback or rollback was blocked due to
        too many recent rollbacks to the same stage.
    """
    if result.type != StageResultType.ROLLBACK_REQUIRED or result.rollback_to is None:
        return False

    task_name = state.task_name
    from_stage = state.stage
    target_stage = result.rollback_to
    reason = result.message

    # Check for rollback loops
    if not state.should_allow_rollback(target_stage):
        from galangal.logging import workflow_logger

        rollback_count = state.get_rollback_count(target_stage)
        loop_msg = (
            f"Rollback loop detected: {rollback_count} rollbacks to {target_stage.value} "
            f"in the last hour. Manual intervention required."
        )
        workflow_logger.rollback(
            from_stage=from_stage.value,
            to_stage=target_stage.value,
            task_name=task_name,
            reason=f"BLOCKED: {loop_msg}",
        )
        return False

    # Record rollback in state history
    state.record_rollback(from_stage, target_stage, reason)

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

    # Log rollback event
    from galangal.logging import workflow_logger

    workflow_logger.rollback(
        from_stage=from_stage.value,
        to_stage=target_stage.value,
        task_name=task_name,
        reason=reason,
    )

    state.stage = target_stage
    state.last_failure = f"Rollback from {from_stage.value}: {reason}"
    state.reset_attempts(clear_failure=False)
    save_state(state)

    return True
