"""
Workflow execution - stage execution, rollback, loop handling.
"""

import signal
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console

from galangal.config.loader import get_config, get_tasks_dir
from galangal.core.artifacts import artifact_exists, read_artifact, write_artifact, artifact_path
from galangal.core.state import (
    Stage,
    WorkflowState,
    STAGE_ORDER,
    save_state,
    get_task_dir,
    should_skip_for_task_type,
)
from galangal.core.tasks import get_current_branch
from galangal.ai.claude import set_pause_requested, get_pause_requested
from galangal.prompts.builder import PromptBuilder
from galangal.validation.runner import ValidationRunner
from galangal.ui.tui import run_stage_with_tui

console = Console()

# Global state for pause handling
_current_state: Optional[WorkflowState] = None


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGINT (Ctrl+C) gracefully."""
    set_pause_requested(True)
    console.print(
        "\n\n[yellow]⏸️  Pause requested - finishing current operation...[/yellow]"
    )
    console.print("[dim]   (Press Ctrl+C again to force quit)[/dim]\n")


def get_next_stage(
    current: Stage, state: WorkflowState
) -> Optional[Stage]:
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


def execute_stage(state: WorkflowState) -> tuple[bool, str]:
    """Execute the current stage. Returns (success, message)."""
    from galangal.commands.approve import prompt_plan_approval, prompt_design_approval

    stage = state.stage
    task_name = state.task_name
    config = get_config()

    if stage == Stage.COMPLETE:
        return True, "Workflow complete"

    # Design approval gate
    if stage == Stage.DEV:
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
        console.print("[dim]Running preflight checks...[/dim]")
        runner = ValidationRunner()
        result = runner.validate_stage("PREFLIGHT", task_name)
        if result.success:
            console.print(f"[green]✓ Preflight: {result.message}[/green]")
            return True, result.message
        else:
            console.print(f"[red]✗ Preflight: {result.message}[/red]")
            console.print("[yellow]  Fix environment issues before continuing.[/yellow]")
            return False, result.message

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

    # Run stage with TUI
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
    console.print("[dim]Validating stage outputs...[/dim]")
    runner = ValidationRunner()
    result = runner.validate_stage(stage.value, task_name)

    with open(log_file, "a") as f:
        f.write(f"\n=== Validation ===\n{result.message}\n")

    if result.success:
        console.print(f"[green]✓ {result.message}[/green]")
    else:
        console.print(f"[red]✗ {result.message}[/red]")

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
    runner = ValidationRunner()

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


def run_workflow(state: WorkflowState) -> None:
    """Run the workflow from current state to completion or failure."""
    from galangal.commands.approve import prompt_plan_approval
    from galangal.commands.complete import finalize_task

    global _current_state
    config = get_config()
    max_retries = config.stages.max_retries

    _current_state = state
    original_handler = signal.signal(signal.SIGINT, _signal_handler)

    try:
        while True:
            # Run stages until COMPLETE
            while state.stage != Stage.COMPLETE:
                if get_pause_requested():
                    _handle_pause(state)
                    return

                success, message = execute_stage(state)

                if get_pause_requested() or message == "PAUSED: User requested pause":
                    _handle_pause(state)
                    return

                if not success:
                    if state.awaiting_approval or state.clarification_required:
                        console.print(f"\n{message}")
                        save_state(state)
                        return

                    if handle_rollback(state, message):
                        continue

                    state.attempt += 1
                    state.last_failure = message

                    if state.attempt > max_retries:
                        console.print(
                            f"\n[red]Max retries ({max_retries}) exceeded for stage {state.stage.value}[/red]"
                        )
                        console.print(f"Last failure: {message}")
                        save_state(state)
                        return

                    console.print(
                        f"\n[yellow]Stage failed, retrying (attempt {state.attempt}/{max_retries})...[/yellow]"
                    )
                    console.print(f"Failure: {message[:500]}...")
                    save_state(state)
                    continue

                console.print(
                    f"\n[green]Stage {state.stage.value} completed successfully[/green]"
                )

                # Plan approval gate
                if state.stage == Stage.PM and not artifact_exists("APPROVAL.md", state.task_name):
                    result = prompt_plan_approval(state.task_name, state)
                    if result == "quit":
                        _handle_pause(state)
                        return
                    elif result == "rejected":
                        continue

                if state.stage == Stage.DEV:
                    archive_rollback_if_exists(state.task_name)

                next_stage = get_next_stage(state.stage, state)
                if next_stage:
                    expected_next_idx = STAGE_ORDER.index(state.stage) + 1
                    actual_next_idx = STAGE_ORDER.index(next_stage)
                    if actual_next_idx > expected_next_idx:
                        skipped = STAGE_ORDER[expected_next_idx:actual_next_idx]
                        for s in skipped:
                            console.print(
                                f"   [dim]⏭️  Skipped {s.value} (condition not met)[/dim]"
                            )

                    state.stage = next_stage
                    state.attempt = 1
                    state.last_failure = None
                    state.awaiting_approval = False
                    state.clarification_required = False
                    save_state(state)
                else:
                    state.stage = Stage.COMPLETE
                    save_state(state)

            # Workflow complete
            console.print("\n" + "=" * 60)
            console.print("[bold green]WORKFLOW COMPLETE[/bold green]")
            console.print("=" * 60)

            from galangal.commands.complete import finalize_task
            from rich.prompt import Prompt

            console.print("\n[bold]Options:[/bold]")
            console.print("  [green]y[/green] - Create PR and finalize")
            console.print("  [yellow]n[/yellow] - Review and make changes (go back to DEV)")
            console.print("  [yellow]q[/yellow] - Quit (finalize later with 'galangal complete')")

            while True:
                choice = Prompt.ask("Your choice", default="y").strip().lower()

                if choice in ["y", "yes"]:
                    finalize_task(state.task_name, state, force=False)
                    return
                elif choice in ["n", "no"]:
                    state.stage = Stage.DEV
                    state.attempt = 1
                    save_state(state)
                    console.print("\n[dim]Going back to DEV stage...[/dim]")
                    break
                elif choice in ["q", "quit"]:
                    _handle_pause(state)
                    return
                else:
                    console.print("[red]Invalid choice. Enter y/n/q[/red]")

    finally:
        signal.signal(signal.SIGINT, original_handler)
        _current_state = None


def _handle_pause(state: WorkflowState) -> None:
    """Handle a pause request."""
    set_pause_requested(False)
    save_state(state)

    console.print("\n" + "=" * 60)
    console.print("[yellow]⏸️  TASK PAUSED[/yellow]")
    console.print("=" * 60)
    console.print(f"\nTask: {state.task_name}")
    console.print(f"Stage: {state.stage.value} (attempt {state.attempt})")
    console.print("\nYour progress has been saved. You can safely shut down now.")
    console.print("\nTo resume later, run:")
    console.print("  [cyan]galangal resume[/cyan]")
    console.print("=" * 60)
