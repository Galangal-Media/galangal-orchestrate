"""
Core workflow utilities - stage execution, rollback handling.
"""

from datetime import datetime, timezone

from rich.console import Console

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
from galangal.core.tasks import get_current_branch
from galangal.prompts.builder import PromptBuilder
from galangal.ui.tui import TUIAdapter, WorkflowTUIApp, run_stage_with_tui
from galangal.validation.runner import ValidationRunner

console = Console()


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


def execute_stage(state: WorkflowState, tui_app: WorkflowTUIApp = None) -> tuple[bool, str]:
    """Execute the current stage. Returns (success, message).

    If tui_app is provided, uses the persistent TUI instead of creating a new one.
    """
    stage = state.stage
    task_name = state.task_name

    if stage == Stage.COMPLETE:
        return True, "Workflow complete"

    # Design approval gate (only in legacy mode without TUI)
    if stage == Stage.DEV and tui_app is None:
        from galangal.commands.approve import prompt_design_approval

        design_skipped = artifact_exists(
            "DESIGN_SKIP.md", task_name
        ) or should_skip_for_task_type(Stage.DESIGN, state.task_type)

        if design_skipped:
            pass
        elif not artifact_exists("DESIGN_REVIEW.md", task_name):
            result = prompt_design_approval(task_name, state)
            if result == "quit":
                return False, "PAUSED: User requested pause"
            elif result == "rejected":
                return True, "Design rejected - restarting from DESIGN"

    # Check for clarification
    if artifact_exists("QUESTIONS.md", task_name) and not artifact_exists(
        "ANSWERS.md", task_name
    ):
        state.clarification_required = True
        save_state(state)
        return False, "Clarification required. Please provide ANSWERS.md."

    # PREFLIGHT runs validation directly
    if stage == Stage.PREFLIGHT:
        if tui_app:
            tui_app.add_activity("Running preflight checks...", "⚙")
        else:
            console.print("[dim]Running preflight checks...[/dim]")

        runner = ValidationRunner()
        result = runner.validate_stage("PREFLIGHT", task_name)

        if result.success:
            if tui_app:
                tui_app.show_message(f"Preflight: {result.message}", "success")
            else:
                console.print(f"[green]✓ Preflight: {result.message}[/green]")
            return True, result.message
        else:
            # Include detailed output in the failure message for display
            detailed_message = result.message
            if result.output:
                detailed_message = f"{result.message}\n\n{result.output}"
            # Return special marker so workflow knows this is preflight failure
            return False, f"PREFLIGHT_FAILED:{detailed_message}"

    # Get current branch for UI
    branch = get_current_branch()

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

    # Run stage - either with persistent TUI or standalone
    if tui_app:
        # Use the persistent TUI
        backend = ClaudeBackend()
        ui = TUIAdapter(tui_app)
        success, output = backend.invoke(
            prompt=prompt,
            timeout=14400,
            max_turns=200,
            ui=ui,
        )
    else:
        # Create new TUI for this stage
        success, output = run_stage_with_tui(
            task_name=task_name,
            stage=stage.value,
            branch=branch,
            attempt=state.attempt,
            prompt=prompt,
        )

    # Log the output
    with open(log_file, "a") as f:
        f.write(f"=== Output ===\n{output}\n")

    if not success:
        return False, output

    # Validate stage
    if tui_app:
        tui_app.add_activity("Validating stage outputs...", "⚙")
    else:
        console.print("[dim]Validating stage outputs...[/dim]")

    runner = ValidationRunner()
    result = runner.validate_stage(stage.value, task_name)

    with open(log_file, "a") as f:
        f.write(f"\n=== Validation ===\n{result.message}\n")

    if result.success:
        if tui_app:
            tui_app.show_message(result.message, "success")
        else:
            console.print(f"[green]✓ {result.message}[/green]")
    else:
        if tui_app:
            tui_app.show_message(result.message, "error")
        else:
            console.print(f"[red]✗ {result.message}[/red]")

    # Include rollback target in message if validation failed
    if not result.success and result.rollback_to:
        return False, f"ROLLBACK:{result.rollback_to}:{result.message}"

    return result.success, result.message


def archive_rollback_if_exists(task_name: str) -> None:
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

    console.print("   [dim]📋 Archived ROLLBACK.md → ROLLBACK_RESOLVED.md[/dim]")


def handle_rollback(state: WorkflowState, message: str) -> bool:
    """Handle a rollback signal from a stage validator."""
    # Check for rollback_to in validation result
    if not message.startswith("ROLLBACK:") and "rollback" not in message.lower():
        return False

    # Parse rollback target
    target_stage = Stage.DEV  # Default rollback target

    if message.startswith("ROLLBACK:"):
        parts = message.split(":", 2)
        if len(parts) >= 2:
            try:
                target_stage = Stage.from_str(parts[1])
            except ValueError:
                pass

    task_name = state.task_name
    from_stage = state.stage

    reason = message.split(":", 2)[-1] if ":" in message else message

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

    console.print(
        f"\n[yellow]⚠️  ROLLBACK: {from_stage.value} → {target_stage.value}[/yellow]"
    )
    console.print(f"   Reason: {reason}")
    console.print("   See ROLLBACK.md for details\n")

    return True
