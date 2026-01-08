"""
galangal approve - Record approval for plans and designs.
"""

import argparse
from datetime import datetime, timezone

from rich.prompt import Prompt

from galangal.core.artifacts import artifact_exists, read_artifact, write_artifact
from galangal.core.state import Stage, load_state, save_state
from galangal.core.tasks import get_active_task
from galangal.core.workflow import run_workflow
from galangal.ui.console import console, print_error, print_info, print_success


def prompt_plan_approval(task_name: str, state) -> str:
    """
    Interactive approval prompt for PLAN.md.
    Returns: 'approved', 'rejected', or 'quit'
    """
    console.print("\n" + "=" * 60)
    console.print("[bold yellow]⏸️  APPROVAL REQUIRED[/bold yellow]")
    console.print("=" * 60)
    console.print(f"\nTask: {task_name}")
    console.print("Stage: PM → [yellow]APPROVAL GATE[/yellow] → DESIGN")

    # Show PLAN.md content
    plan = read_artifact("PLAN.md", task_name)
    if plan:
        console.print("\n[bold]PLAN.md Preview:[/bold]")
        console.print("[dim]" + "-" * 40 + "[/dim]")
        # Show first 1500 chars
        preview = plan[:1500] + ("..." if len(plan) > 1500 else "")
        console.print(preview)
        console.print("[dim]" + "-" * 40 + "[/dim]")

    console.print("\n[bold]Options:[/bold]")
    console.print("  [green]y[/green] - Approve plan and continue to DESIGN")
    console.print("  [red]n[/red] - Reject and restart PM stage")
    console.print("  [yellow]q[/yellow] - Quit/pause (resume later)")

    while True:
        choice = Prompt.ask("Your choice", default="y").strip().lower()

        if choice in ["y", "yes", "approve"]:
            approver = Prompt.ask("Approver name", default="")

            approval_content = f"""# Plan Approval

- **Status:** Approved
- **Approved By:** {approver or "Not specified"}
- **Date:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
"""
            write_artifact("APPROVAL.md", approval_content, task_name)
            print_success("Plan approved!")
            return "approved"

        elif choice in ["n", "no", "reject"]:
            reason = Prompt.ask("Rejection reason", default="Needs revision")
            state.stage = Stage.PM
            state.last_failure = f"Plan rejected: {reason}"
            state.reset_attempts(clear_failure=False)
            save_state(state)
            print_info("Plan rejected. Restarting PM stage.")
            return "rejected"

        elif choice in ["q", "quit", "pause"]:
            return "quit"

        else:
            print_error("Invalid choice. Enter y/n/q")


def prompt_design_approval(task_name: str, state) -> str:
    """
    Interactive approval prompt for DESIGN.md.
    Returns: 'approved', 'rejected', or 'quit'
    """
    console.print("\n" + "=" * 60)
    console.print("[bold yellow]⏸️  DESIGN REVIEW REQUIRED[/bold yellow]")
    console.print("=" * 60)
    console.print(f"\nTask: {task_name}")
    console.print("Stage: DESIGN → [yellow]REVIEW GATE[/yellow] → DEV")

    # Show DESIGN.md content
    design = read_artifact("DESIGN.md", task_name)
    if design:
        console.print("\n[bold]DESIGN.md Preview:[/bold]")
        console.print("[dim]" + "-" * 40 + "[/dim]")
        preview = design[:2000] + ("..." if len(design) > 2000 else "")
        console.print(preview)
        console.print("[dim]" + "-" * 40 + "[/dim]")

    console.print("\n[bold]Options:[/bold]")
    console.print("  [green]y[/green] - Approve design and continue to DEV")
    console.print("  [red]n[/red] - Reject and restart DESIGN stage")
    console.print("  [yellow]q[/yellow] - Quit/pause (resume later)")

    while True:
        choice = Prompt.ask("Your choice", default="y").strip().lower()

        if choice in ["y", "yes", "approve"]:
            approver = Prompt.ask("Reviewer name", default="")

            review_content = f"""# Design Review

**Status:** Approved
**Date:** {datetime.now(timezone.utc).isoformat()}
**Reviewer:** {approver or "Not specified"}

## Review Notes

Design reviewed and approved for implementation.
"""
            write_artifact("DESIGN_REVIEW.md", review_content, task_name)
            print_success("Design approved!")
            return "approved"

        elif choice in ["n", "no", "reject"]:
            reason = Prompt.ask("Rejection reason", default="Needs revision")
            state.stage = Stage.DESIGN
            state.last_failure = f"Design rejected: {reason}"
            state.reset_attempts(clear_failure=False)
            save_state(state)
            print_info("Design rejected. Restarting DESIGN stage.")
            return "rejected"

        elif choice in ["q", "quit", "pause"]:
            return "quit"

        else:
            print_error("Invalid choice. Enter y/n/q")


def cmd_approve(args: argparse.Namespace) -> int:
    """Record human approval for active task (fallback command)."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    if state.stage != Stage.DESIGN or artifact_exists("APPROVAL.md", active):
        print_error("Approval not needed at this stage.")
        return 1

    result = prompt_plan_approval(active, state)
    if result == "approved":
        run_workflow(state)
    return 0 if result == "approved" else 1


def cmd_approve_design(args: argparse.Namespace) -> int:
    """Record design review approval for active task (fallback command)."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    if state.stage != Stage.DEV:
        print_error(
            f"Design approval is for DEV stage. Current stage: {state.stage.value}"
        )
        return 1

    if artifact_exists("DESIGN_REVIEW.md", active):
        print_error("DESIGN_REVIEW.md already exists.")
        return 1

    if not artifact_exists("DESIGN.md", active):
        print_error("DESIGN.md not found. Design stage may not have completed.")
        return 1

    result = prompt_design_approval(active, state)
    if result == "approved":
        run_workflow(state)
    return 0 if result == "approved" else 1
