"""
Core workflow utilities - stage execution, rollback handling.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from galangal.ai import get_backend_for_stage
from galangal.ai.base import PauseCheck
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
from galangal.core.utils import now_iso
from galangal.prompts.builder import PromptBuilder
from galangal.results import StageResult, StageResultType
from galangal.ui.tui import TUIAdapter
from galangal.validation.runner import ValidationRunner

if TYPE_CHECKING:
    from galangal.ui.tui import WorkflowTUIApp


# Get conditional stages from metadata (cached at module load)
CONDITIONAL_STAGES: dict[Stage, str] = get_conditional_stages()


def _format_issues(issues: list[dict[str, Any]]) -> str:
    """Format issues list into markdown."""
    if not issues:
        return ""

    formatted = "\n\n## Issues Found\n\n"
    for issue in issues:
        severity = issue.get("severity", "unknown")
        desc = issue.get("description", "")
        file_ref = issue.get("file", "")
        line = issue.get("line")
        loc = f" ({file_ref}:{line})" if file_ref and line else ""
        formatted += f"- **[{severity.upper()}]** {desc}{loc}\n"
    return formatted


def _write_artifacts_from_readonly_output(
    stage: Stage,
    output: str,
    task_name: str,
    tui_app: WorkflowTUIApp,
) -> None:
    """
    Write stage artifacts from read-only backend's structured JSON output.

    Read-only backends (like Codex) cannot write files directly. Instead,
    they return structured JSON which we post-process to create the expected
    artifacts based on STAGE_ARTIFACT_SCHEMA.

    Supports two modes:
    1. Schema-based: Uses STAGE_METADATA artifact_schema mapping
    2. Generic fallback: Looks for 'artifacts' array in JSON output

    Args:
        stage: The stage that was executed
        output: JSON string containing structured output
        task_name: Task name for artifact paths
        tui_app: TUI app for activity logging
    """
    import json

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        tui_app.add_activity("Warning: Backend output is not valid JSON", "⚠️")
        return

    # Try schema-based artifact writing first
    schema = stage.metadata.artifact_schema
    if schema:
        _write_schema_artifacts(data, schema, stage, task_name, tui_app)
        return

    # Fall back to generic artifacts array
    artifacts = data.get("artifacts", [])
    if artifacts:
        _write_generic_artifacts(artifacts, task_name, tui_app)
    else:
        tui_app.add_activity(f"Warning: No artifact schema for {stage.value}", "⚠️")


def _write_schema_artifacts(
    data: dict[str, Any],
    schema: dict[str, str | None],
    stage: Stage,
    task_name: str,
    tui_app: WorkflowTUIApp,
) -> None:
    """Write artifacts based on stage schema mapping."""
    from galangal.core.state import get_decision_values

    notes_file = schema.get("notes_file")
    notes_field = schema.get("notes_field")
    decision_file = schema.get("decision_file")
    decision_field = schema.get("decision_field")
    issues_field = schema.get("issues_field")

    # Write notes file
    if notes_file and notes_field:
        notes = data.get(notes_field, "")
        if notes:
            # Append formatted issues if present
            if issues_field:
                issues = data.get(issues_field, [])
                notes += _format_issues(issues)

            write_artifact(notes_file, notes, task_name)
            tui_app.add_activity(f"Wrote {notes_file} from backend output", "📝")

    # Write decision file using stage-specific valid values
    if decision_file and decision_field:
        decision = data.get(decision_field, "")
        # Get valid decisions from STAGE_METADATA
        valid_decisions = get_decision_values(stage)
        if decision in valid_decisions:
            write_artifact(decision_file, decision, task_name)
            tui_app.add_activity(f"Wrote {decision_file}: {decision}", "📝")
        elif decision:
            tui_app.add_activity(
                f"Warning: Invalid decision '{decision}' for {stage.value} "
                f"(expected: {', '.join(valid_decisions)})",
                "⚠️",
            )


def _write_generic_artifacts(
    artifacts: list[dict[str, Any]],
    task_name: str,
    tui_app: WorkflowTUIApp,
) -> None:
    """Write artifacts from generic artifacts array in JSON output.

    Expected format:
    [
        {"name": "ARTIFACT_NAME.md", "content": "..."},
        ...
    ]
    """
    for artifact in artifacts:
        name = artifact.get("name")
        content = artifact.get("content")
        if name and content:
            write_artifact(name, content, task_name)
            tui_app.add_activity(f"Wrote {name} from backend output", "📝")


def get_next_stage(current: Stage, state: WorkflowState) -> Stage | None:
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

    # Check fast-track skipping (minor rollback - skip stages that already passed)
    if state.should_fast_track_skip(next_stage):
        return get_next_stage(next_stage, state)

    # Check PM-driven stage plan (STAGE_PLAN.md recommendations)
    if state.stage_plan and next_stage.value in state.stage_plan:
        plan_entry = state.stage_plan[next_stage.value]
        if plan_entry.get("action") == "skip":
            return get_next_stage(next_stage, state)

    # Check conditional stages (MIGRATION, CONTRACT, BENCHMARK)
    if next_stage in CONDITIONAL_STAGES:
        skip_artifact = CONDITIONAL_STAGES[next_stage]

        # Manual skip artifacts ALWAYS win (user explicitly ran galangal skip-*)
        if artifact_exists(skip_artifact, task_name):
            return get_next_stage(next_stage, state)

        # If PM explicitly said "run", don't apply glob-based skipping
        if state.stage_plan and next_stage.value in state.stage_plan:
            plan_entry = state.stage_plan[next_stage.value]
            if plan_entry.get("action") == "run":
                return next_stage  # PM says run, skip the glob check

        # Check glob-based skip conditions
        runner = ValidationRunner()
        if runner.should_skip_stage(next_stage.value.upper(), task_name):
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
        return StageResult.create_success("Workflow complete")

    # Check skip conditions BEFORE building prompts or invoking AI
    # This avoids wasted execution when a stage should be skipped
    runner = ValidationRunner()
    if runner.should_skip_stage(stage.value.upper(), task_name):
        from galangal.core.artifacts import write_skip_artifact

        write_skip_artifact(stage.value, "skip_if condition met", task_name)
        tui_app.add_activity(f"{stage.value} skipped (condition met)", "⏭")
        workflow_logger.stage_completed(
            stage=stage.value,
            task_name=task_name,
            success=True,
            skipped=True,
        )
        return StageResult.skipped(f"{stage.value} skipped (condition met)")

    # Check for clarification
    if artifact_exists("QUESTIONS.md", task_name) and not artifact_exists("ANSWERS.md", task_name):
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
            return StageResult.create_success(result.message)
        else:
            return StageResult.preflight_failed(
                message=result.message,
                details=result.output or "",
            )

    # Get backend first (needed for backend-specific prompts)
    backend = get_backend_for_stage(stage, config, use_fallback=True)

    # Build prompt
    builder = PromptBuilder()

    # For read-only backends on review-type stages, use minimal context
    # This gives an unbiased review without Claude's interpretations
    review_stages = {Stage.REVIEW, Stage.SECURITY, Stage.QA}
    if backend.read_only and stage in review_stages:
        prompt = builder.build_minimal_review_prompt(state, backend_name=backend.name)
        tui_app.add_activity("Using minimal context for independent review", "📋")
    else:
        prompt = builder.build_full_prompt(stage, state, backend_name=backend.name)

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
    tui_app.add_activity(f"Using {backend.name} backend", "🤖")

    ui = TUIAdapter(tui_app)
    max_turns = backend.config.max_turns if backend.config else 200
    invoke_result = backend.invoke(
        prompt=prompt,
        timeout=config.stages.timeout,
        max_turns=max_turns,
        ui=ui,
        pause_check=pause_check,
        stage=stage.value,
    )

    # Log the output
    with open(log_file, "a") as f:
        f.write(f"=== Backend: {backend.name} ===\n")
        f.write(f"=== Output ===\n{invoke_result.output or invoke_result.message}\n")

    # Return early if AI invocation failed
    if not invoke_result.success:
        return invoke_result

    # Post-process for read-only backends (e.g., Codex)
    # These backends return structured JSON instead of writing files directly
    if backend.read_only and invoke_result.output:
        _write_artifacts_from_readonly_output(stage, invoke_result.output, task_name, tui_app)

    # Validate stage
    tui_app.add_activity("Validating stage outputs...", "⚙")

    runner = ValidationRunner()
    result = runner.validate_stage(stage.value, task_name)

    # Log validation details including rollback_to for debugging
    with open(log_file, "a") as f:
        f.write("\n=== Validation ===\n")
        f.write(f"success: {result.success}\n")
        f.write(f"message: {result.message}\n")
        f.write(f"rollback_to: {result.rollback_to}\n")
        f.write(f"skipped: {result.skipped}\n")
        if result.output:
            f.write(f"\n=== Validation Output ===\n{result.output}\n")

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
        return StageResult.create_success(result.message, output=invoke_result.output)
    else:
        # Check if user decision is needed (decision file missing)
        if result.needs_user_decision:
            tui_app.add_activity("Decision file missing - user confirmation required", "❓")
            return StageResult.user_decision_needed(
                message=result.message,
                artifact_content=result.output,
            )

        tui_app.show_message(result.message, "error")
        workflow_logger.stage_failed(
            stage=stage.value,
            task_name=task_name,
            error=result.message,
            attempt=state.attempt,
        )
        # Check if rollback is required
        if result.rollback_to:
            rollback_type = "fast-track rollback" if result.is_fast_track else "rollback"
            tui_app.add_activity(f"Triggering {rollback_type} to {result.rollback_to}", "🔄")
            return StageResult.rollback_required(
                message=result.message,
                rollback_to=Stage.from_str(result.rollback_to),
                output=invoke_result.output,
                is_fast_track=result.is_fast_track,
            )
        # Log when rollback_to is not set (helps debug missing rollback)
        tui_app.add_activity("Validation failed without rollback target", "⚠")
        return StageResult.validation_failed(result.message)


def append_rollback_entry(
    task_name: str,
    source: str,
    from_stage: str,
    target_stage: str,
    reason: str,
) -> None:
    """
    Append a rollback entry to ROLLBACK.md, preserving history.

    Creates a structured entry documenting the rollback event and appends it
    to existing ROLLBACK.md content (or creates new file if none exists).

    Args:
        task_name: Name of the task.
        source: Description of what triggered the rollback
            (e.g., "User interrupt (Ctrl+I)", "Validation failure", "Manual review").
        from_stage: Stage where the rollback was triggered.
        target_stage: Stage to roll back to.
        reason: Description of issues to fix.
    """
    rollback_entry = f"""
---

## {source}

**Date:** {now_iso()}
**From Stage:** {from_stage}
**Target Stage:** {target_stage}

### Issues to Fix
{reason}
"""

    existing = read_artifact("ROLLBACK.md", task_name)
    if existing:
        new_content = existing + rollback_entry
    else:
        new_content = f"# Rollback Log\n\nThis file tracks issues that required rolling back to earlier stages.\n{rollback_entry}"

    write_artifact("ROLLBACK.md", new_content, task_name)


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

    rollback_content = read_artifact("ROLLBACK.md", task_name) or ""
    resolved_path = artifact_path("ROLLBACK_RESOLVED.md", task_name)

    resolution_note = f"\n\n## Resolved: {now_iso()}\n\nIssues fixed by DEV stage.\n"

    if resolved_path.exists():
        existing = resolved_path.read_text()
        resolved_path.write_text(existing + "\n---\n" + rollback_content + resolution_note)
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

    # Append to ROLLBACK.md
    append_rollback_entry(
        task_name=task_name,
        source=f"Validation failure in {from_stage.value}",
        from_stage=from_stage.value,
        target_stage=target_stage.value,
        reason=reason,
    )

    # Log rollback event
    from galangal.logging import workflow_logger

    workflow_logger.rollback(
        from_stage=from_stage.value,
        to_stage=target_stage.value,
        task_name=task_name,
        reason=reason,
    )

    # Handle fast-track vs full rollback
    if result.is_fast_track:
        # Minor rollback: skip stages that already passed
        state.setup_fast_track()
    else:
        # Full rollback: re-run all stages
        state.clear_fast_track()
        state.clear_passed_stages()

    state.stage = target_stage
    state.last_failure = f"Rollback from {from_stage.value}: {reason}"
    state.reset_attempts(clear_failure=False)
    save_state(state)

    return True
