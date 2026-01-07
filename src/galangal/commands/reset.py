"""
galangal reset - Delete the active task.
"""

import argparse
import shutil

from rich.prompt import Prompt

from galangal.core.state import get_task_dir
from galangal.core.tasks import clear_active_task, get_active_task
from galangal.ui.console import print_error, print_info, print_success


def cmd_reset(args: argparse.Namespace) -> int:
    """Delete the active task."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 0

    task_dir = get_task_dir(active)
    if not task_dir.exists():
        print_info("Task directory not found.")
        clear_active_task()
        return 0

    if not args.force:
        confirm = (
            Prompt.ask(
                f"Delete task '{active}' and all its artifacts? [y/N]", default="n"
            )
            .strip()
            .lower()
        )
        if confirm != "y":
            print_info("Reset cancelled.")
            return 1

    shutil.rmtree(task_dir)
    clear_active_task()
    print_success(f"Task '{active}' deleted.")
    return 0
