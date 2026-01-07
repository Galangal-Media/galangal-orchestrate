"""
galangal switch - Switch to a different task.
"""

import argparse

from galangal.core.state import get_task_dir, load_state
from galangal.core.tasks import set_active_task
from galangal.ui.console import console, print_error, print_success


def cmd_switch(args: argparse.Namespace) -> int:
    """Switch to a different task."""
    task_name = args.task_name
    task_dir = get_task_dir(task_name)

    if not task_dir.exists():
        print_error(f"Task '{task_name}' not found.")
        return 1

    set_active_task(task_name)
    state = load_state(task_name)
    if state:
        print_success(f"Switched to: {task_name}")
        console.print(f"[dim]Stage:[/dim] {state.stage.value}")
        console.print(f"[dim]Type:[/dim] {state.task_type.display_name()}")
        console.print(f"[dim]Description:[/dim] {state.task_description[:60]}...")
    return 0
