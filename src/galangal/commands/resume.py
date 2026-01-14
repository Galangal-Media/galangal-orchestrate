"""
galangal resume - Resume the active task.
"""

import argparse

from galangal.core.tasks import ensure_active_task_with_state
from galangal.core.workflow import run_workflow
from galangal.ui.console import console


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume the active task."""
    active, state = ensure_active_task_with_state(
        no_task_msg="No active task. Use 'list' to see tasks, 'switch' to select one."
    )
    if not active or not state:
        return 1

    console.print(f"[bold]Resuming task:[/bold] {active}")
    console.print(f"[dim]Stage:[/dim] {state.stage.value}")
    console.print(f"[dim]Type:[/dim] {state.task_type.display_name()}")

    # Pass skip_discovery flag via state attribute
    if getattr(args, 'skip_discovery', False):
        state._skip_discovery = True
        console.print("[dim]Discovery Q&A:[/dim] skipped")

    run_workflow(state)
    return 0
