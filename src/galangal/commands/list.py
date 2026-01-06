"""
galangal list - List all tasks.
"""

import argparse

from galangal.core.tasks import get_active_task, list_tasks
from galangal.ui.console import console, display_task_list


def cmd_list(args: argparse.Namespace) -> int:
    """List all tasks."""
    tasks = list_tasks()
    active = get_active_task()

    display_task_list(tasks, active)

    if active:
        console.print("\n[dim]→ = active task[/dim]")
    return 0
