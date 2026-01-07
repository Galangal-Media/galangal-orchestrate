"""
galangal status - Show active task status.
"""

import argparse

from galangal.core.artifacts import artifact_exists
from galangal.core.state import load_state
from galangal.core.tasks import get_active_task
from galangal.ui.console import display_status, print_error, print_info


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of active task."""
    active = get_active_task()
    if not active:
        print_info("No active task. Use 'list' to see tasks, 'switch' to select one.")
        return 0

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    # Collect artifact status
    artifacts = []
    for name in [
        "SPEC.md",
        "PLAN.md",
        "APPROVAL.md",
        "DESIGN.md",
        "DESIGN_REVIEW.md",
        "DESIGN_SKIP.md",
        "PREFLIGHT_REPORT.md",
        "MIGRATION_REPORT.md",
        "MIGRATION_SKIP.md",
        "TEST_PLAN.md",
        "CONTRACT_REPORT.md",
        "CONTRACT_SKIP.md",
        "QA_REPORT.md",
        "BENCHMARK_REPORT.md",
        "BENCHMARK_SKIP.md",
        "SECURITY_CHECKLIST.md",
        "SECURITY_SKIP.md",
        "REVIEW_NOTES.md",
        "DOCS_REPORT.md",
        "ROLLBACK.md",
    ]:
        artifacts.append((name, artifact_exists(name, active)))

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
