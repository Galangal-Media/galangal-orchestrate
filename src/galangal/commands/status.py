"""
galangal status - Show active task status.
"""

import argparse

from galangal.core.artifacts import artifact_exists
from galangal.core.tasks import get_active_task
from galangal.ui.console import display_status, print_error, print_info


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of active task."""
    from galangal.config.loader import require_initialized
    from galangal.core.state import get_all_artifact_names, load_state

    if not require_initialized():
        return 1

    active = get_active_task()
    if not active:
        print_info("No active task. Use 'list' to see tasks, 'switch' to select one.")
        return 0

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    # Collect artifact status - derived from STAGE_METADATA
    artifacts = [(name, artifact_exists(name, active)) for name in get_all_artifact_names()]

    display_status(
        task_name=active,
        stage=state.stage,
        task_type=state.task_type,
        attempt=state.attempt,
        awaiting_approval=state.awaiting_approval,
        last_failure=state.last_failure,
        description=state.task_description,
        artifacts=artifacts,
    )

    return 0
