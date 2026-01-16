"""
galangal skip-to - Jump to a specific stage for debugging.
"""

import argparse

from rich.prompt import Prompt

from galangal.core.state import STAGE_ORDER, parse_stage_arg, save_state
from galangal.core.tasks import ensure_active_task_with_state
from galangal.core.workflow import run_workflow
from galangal.ui.console import console, print_info, print_success


def cmd_skip_to(args: argparse.Namespace) -> int:
    """Jump to a specific stage (for debugging/re-running)."""
    active, state = ensure_active_task_with_state()
    if not active or not state:
        return 1

    # Parse target stage (COMPLETE not allowed - use 'complete' command instead)
    target_stage = parse_stage_arg(args.stage, exclude_complete=True)
    if target_stage is None:
        return 1

    current_stage = state.stage
    current_idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else -1
    target_idx = STAGE_ORDER.index(target_stage)

    # Warn if skipping backwards or forwards
    if target_idx < current_idx:
        console.print(
            f"[yellow]⚠️  Going backwards: {current_stage.value} → {target_stage.value}[/yellow]"
        )
    elif target_idx > current_idx:
        console.print(
            f"[yellow]⚠️  Skipping forward: {current_stage.value} → {target_stage.value}[/yellow]"
        )
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
