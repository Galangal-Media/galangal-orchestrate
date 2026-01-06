"""
galangal resume - Resume the active task.
"""

import argparse

from galangal.core.state import load_state
from galangal.core.tasks import get_active_task
from galangal.core.workflow import run_workflow
from galangal.ui.console import console, print_error


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume the active task."""
    active = get_active_task()
    if not active:
        print_error("No active task. Use 'list' to see tasks, 'switch' to select one.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    console.print(f"[bold]Resuming task:[/bold] {active}")
    console.print(f"[dim]Stage:[/dim] {state.stage.value}")
    console.print(f"[dim]Type:[/dim] {state.task_type.display_name()}")
    run_workflow(state)
    return 0
