"""
galangal pause - Pause the active task.
"""

import argparse

from galangal.core.state import Stage
from galangal.core.tasks import ensure_active_task_with_state
from galangal.ui.console import console, print_info


def cmd_pause(args: argparse.Namespace) -> int:
    """Pause the active task for a break or shutdown."""
    active, state = ensure_active_task_with_state()
    if not active or not state:
        return 1

    if state.stage == Stage.COMPLETE:
        print_info(f"Task '{active}' is already complete.")
        console.print("Use 'complete' to create PR and move to done/.")
        return 0

    console.print("\n" + "=" * 60)
    console.print("[yellow]⏸️  TASK PAUSED[/yellow]")
    console.print("=" * 60)
    console.print(f"\nTask: {state.task_name}")
    console.print(f"Stage: {state.stage.value} (attempt {state.attempt})")
    console.print(f"Type: {state.task_type.display_name()}")
    console.print(f"Description: {state.task_description[:60]}...")
    console.print("\nYour progress is saved. You can safely shut down now.")
    console.print("\nTo resume later, run:")
    console.print("  [cyan]galangal resume[/cyan]")
    console.print("=" * 60)
    return 0
