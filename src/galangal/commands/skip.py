"""
galangal skip-* commands - Skip various stages.
"""

import argparse
from datetime import datetime, timezone

from rich.prompt import Prompt

from galangal.core.artifacts import artifact_exists, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    TASK_TYPE_SKIP_STAGES,
    Stage,
    load_state,
    save_state,
)
from galangal.core.tasks import get_active_task
from galangal.core.workflow import run_workflow
from galangal.ui.console import console, print_error, print_info, print_success


def _skip_stage(
    stage: Stage,
    skip_artifact: str,
    prompt_text: str,
    default_reason: str,
) -> int:
    """Generic skip stage handler."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    if artifact_exists(skip_artifact, active):
        print_info(f"{stage.value} already marked as skipped.")
        return 0

    # Check if task type already skips this stage
    if stage in TASK_TYPE_SKIP_STAGES.get(state.task_type, set()):
        print_info(f"{stage.value} already skipped by task type '{state.task_type.value}'.")
        return 0

    reason = Prompt.ask(prompt_text, default=default_reason).strip()

    skip_content = f"""# {stage.value} Stage Skipped

Date: {datetime.now(timezone.utc).isoformat()}
Reason: {reason}
"""
    write_artifact(skip_artifact, skip_content, active)

    print_success(f"{stage.value} stage marked as skipped: {reason}")

    if state.stage == stage:
        console.print("Resuming workflow...")
        run_workflow(state)

    return 0


def cmd_skip_design(args: argparse.Namespace) -> int:
    """Skip design stage for trivial tasks."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    if state.stage not in [Stage.PM, Stage.DESIGN]:
        print_error(
            f"Can only skip design before or during DESIGN stage. Current: {state.stage.value}"
        )
        return 1

    if artifact_exists("DESIGN_SKIP.md", active):
        print_info("Design already marked as skipped.")
        return 0

    # Check if task type already skips this stage
    if Stage.DESIGN in TASK_TYPE_SKIP_STAGES.get(state.task_type, set()):
        print_info(f"Design already skipped by task type '{state.task_type.value}'.")
        return 0

    reason = Prompt.ask(
        "Reason for skipping design", default="Trivial task, no design needed"
    ).strip()

    skip_content = f"""# Design Stage Skipped

Date: {datetime.now(timezone.utc).isoformat()}
Reason: {reason}
"""
    write_artifact("DESIGN_SKIP.md", skip_content, active)
    write_artifact(
        "APPROVAL.md", f"# Auto-Approval\n\nDesign skipped: {reason}\n", active
    )

    print_success(f"Design stage marked as skipped: {reason}")

    if state.stage == Stage.DESIGN:
        console.print("Resuming workflow...")
        run_workflow(state)

    return 0


def cmd_skip_security(args: argparse.Namespace) -> int:
    """Skip security stage for non-code changes."""
    return _skip_stage(
        Stage.SECURITY,
        "SECURITY_SKIP.md",
        "Reason for skipping security",
        "No code changes",
    )


def cmd_skip_migration(args: argparse.Namespace) -> int:
    """Skip migration stage."""
    return _skip_stage(
        Stage.MIGRATION,
        "MIGRATION_SKIP.md",
        "Reason for skipping migration",
        "No database changes",
    )


def cmd_skip_contract(args: argparse.Namespace) -> int:
    """Skip contract stage."""
    return _skip_stage(
        Stage.CONTRACT,
        "CONTRACT_SKIP.md",
        "Reason for skipping contract",
        "No API changes",
    )


def cmd_skip_benchmark(args: argparse.Namespace) -> int:
    """Skip benchmark stage."""
    return _skip_stage(
        Stage.BENCHMARK,
        "BENCHMARK_SKIP.md",
        "Reason for skipping benchmark",
        "No performance requirements",
    )


def cmd_skip_to(args: argparse.Namespace) -> int:
    """Jump to a specific stage (for debugging/re-running)."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    # Parse target stage
    target_stage_str = args.stage.upper()
    try:
        target_stage = Stage.from_str(target_stage_str)
    except ValueError:
        print_error(f"Invalid stage: '{args.stage}'")
        valid_stages = ", ".join(s.value for s in Stage)
        console.print(f"[dim]Valid stages: {valid_stages}[/dim]")
        return 1

    if target_stage == Stage.COMPLETE:
        print_error("Cannot skip to COMPLETE. Use 'complete' command instead.")
        return 1

    current_stage = state.stage
    current_idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else -1
    target_idx = STAGE_ORDER.index(target_stage)

    # Warn if skipping backwards or forwards
    if target_idx < current_idx:
        console.print(f"[yellow]⚠️  Going backwards: {current_stage.value} → {target_stage.value}[/yellow]")
    elif target_idx > current_idx:
        console.print(f"[yellow]⚠️  Skipping forward: {current_stage.value} → {target_stage.value}[/yellow]")
    else:
        console.print(f"[dim]Re-running current stage: {target_stage.value}[/dim]")

    if not args.force:
        confirm = Prompt.ask(f"Jump to {target_stage.value}? [y/N]", default="n").strip().lower()
        if confirm != "y":
            print_info("Cancelled.")
            return 0

    # Update state
    state.stage = target_stage
    state.reset_attempts()
    state.awaiting_approval = False
    state.clarification_required = False
    save_state(state)

    print_success(f"Jumped to stage: {target_stage.value}")

    # Optionally resume immediately
    if args.resume:
        console.print("\n[dim]Resuming workflow...[/dim]")
        run_workflow(state)

    return 0
