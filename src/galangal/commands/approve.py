"""
galangal approve - Record approval for plans and designs.
"""

import argparse
from dataclasses import dataclass

from rich.prompt import Prompt

from galangal.core.artifacts import artifact_exists, read_artifact, write_artifact
from galangal.core.state import Stage, save_state
from galangal.core.tasks import ensure_active_task_with_state
from galangal.core.utils import now_formatted, now_iso, truncate_text
from galangal.core.workflow import run_workflow
from galangal.ui.console import console, print_error, print_info, print_success


@dataclass
class ApprovalConfig:
    """Configuration for an approval prompt."""

    header: str  # e.g., "APPROVAL REQUIRED"
    artifact_name: str  # e.g., "PLAN.md"
    artifact_label: str  # e.g., "PLAN.md Preview"
    output_artifact: str  # e.g., "APPROVAL.md"
    stage_flow: str  # e.g., "PM → [yellow]APPROVAL GATE[/yellow] → DESIGN"
    approve_msg: str  # e.g., "Approve plan and continue to DESIGN"
    reject_msg: str  # e.g., "Reject and restart PM stage"
    rollback_stage: Stage  # Stage to roll back to on rejection
    success_msg: str  # e.g., "Plan approved!"
    reject_info: str  # e.g., "Plan rejected. Restarting PM stage."
    approver_label: str  # e.g., "Approver name"
    preview_length: int = 1500  # Max chars to show in preview


# Pre-configured approval types
PLAN_APPROVAL = ApprovalConfig(
    header="APPROVAL REQUIRED",
    artifact_name="PLAN.md",
    artifact_label="PLAN.md Preview",
    output_artifact="APPROVAL.md",
    stage_flow="PM → [yellow]APPROVAL GATE[/yellow] → DESIGN",
    approve_msg="Approve plan and continue to DESIGN",
    reject_msg="Reject and restart PM stage",
    rollback_stage=Stage.PM,
    success_msg="Plan approved!",
    reject_info="Plan rejected. Restarting PM stage.",
    approver_label="Approver name",
    preview_length=1500,
)

DESIGN_APPROVAL = ApprovalConfig(
    header="DESIGN REVIEW REQUIRED",
    artifact_name="DESIGN.md",
    artifact_label="DESIGN.md Preview",
    output_artifact="DESIGN_REVIEW.md",
    stage_flow="DESIGN → [yellow]REVIEW GATE[/yellow] → DEV",
    approve_msg="Approve design and continue to DEV",
    reject_msg="Reject and restart DESIGN stage",
    rollback_stage=Stage.DESIGN,
    success_msg="Design approved!",
    reject_info="Design rejected. Restarting DESIGN stage.",
    approver_label="Reviewer name",
    preview_length=2000,
)


def _generate_approval_content(config: ApprovalConfig, approver: str) -> str:
    """Generate approval artifact content based on config type."""
    if config.output_artifact == "APPROVAL.md":
        return f"""# Plan Approval

- **Status:** Approved
- **Approved By:** {approver or "Not specified"}
- **Date:** {now_formatted()}
"""
    else:  # DESIGN_REVIEW.md
        return f"""# Design Review

**Status:** Approved
**Date:** {now_iso()}
**Reviewer:** {approver or "Not specified"}

## Review Notes

Design reviewed and approved for implementation.
"""


def prompt_approval(task_name: str, state, config: ApprovalConfig) -> str:
    """
    Generic interactive approval prompt.

    Args:
        task_name: Name of the task being approved.
        state: WorkflowState to update on rejection.
        config: ApprovalConfig specifying the approval type.

    Returns:
        'approved', 'rejected', or 'quit'
    """
    console.print("\n" + "=" * 60)
    console.print(f"[bold yellow]⏸️  {config.header}[/bold yellow]")
    console.print("=" * 60)
    console.print(f"\nTask: {task_name}")
    console.print(f"Stage: {config.stage_flow}")

    # Show artifact content
    content = read_artifact(config.artifact_name, task_name)
    if content:
        console.print(f"\n[bold]{config.artifact_label}:[/bold]")
        console.print("[dim]" + "-" * 40 + "[/dim]")
        console.print(truncate_text(content, config.preview_length))
        console.print("[dim]" + "-" * 40 + "[/dim]")

    console.print("\n[bold]Options:[/bold]")
    console.print(f"  [green]y[/green] - {config.approve_msg}")
    console.print(f"  [red]n[/red] - {config.reject_msg}")
    console.print("  [yellow]q[/yellow] - Quit/pause (resume later)")

    while True:
        choice = Prompt.ask("Your choice", default="y").strip().lower()

        if choice in ["y", "yes", "approve"]:
            approver = Prompt.ask(config.approver_label, default="")
            approval_content = _generate_approval_content(config, approver)
            write_artifact(config.output_artifact, approval_content, task_name)
            print_success(config.success_msg)
            return "approved"

        elif choice in ["n", "no", "reject"]:
            reason = Prompt.ask("Rejection reason", default="Needs revision")
            state.stage = config.rollback_stage
            state.last_failure = f"{config.artifact_name.replace('.md', '')} rejected: {reason}"
            state.reset_attempts(clear_failure=False)
            save_state(state)
            print_info(config.reject_info)
            return "rejected"

        elif choice in ["q", "quit", "pause"]:
            return "quit"

        else:
            print_error("Invalid choice. Enter y/n/q")


def prompt_plan_approval(task_name: str, state) -> str:
    """Interactive approval prompt for PLAN.md."""
    return prompt_approval(task_name, state, PLAN_APPROVAL)


def prompt_design_approval(task_name: str, state) -> str:
    """Interactive approval prompt for DESIGN.md."""
    return prompt_approval(task_name, state, DESIGN_APPROVAL)


def cmd_approve(args: argparse.Namespace) -> int:
    """Record human approval for active task (fallback command)."""
    active, state = ensure_active_task_with_state()
    if not active or not state:
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
    active, state = ensure_active_task_with_state()
    if not active or not state:
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
