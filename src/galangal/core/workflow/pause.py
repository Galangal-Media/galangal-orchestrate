"""
Pause handling for workflow execution.
"""

from rich.console import Console

from galangal.core.state import Stage, WorkflowState, save_state

console = Console()

# Stages that modify code and benefit from resume context
CODE_MODIFYING_STAGES = {Stage.DEV, Stage.TEST, Stage.DOCS, Stage.REVIEW}


def _handle_pause(state: WorkflowState) -> None:
    """Handle a pause request. Called after TUI exits."""
    # Add resume context for stages that modify code
    if state.stage in CODE_MODIFYING_STAGES and not state.last_failure:
        state.last_failure = (
            "Stage was interrupted mid-execution. "
            "Run `git status` and `git diff` to see any work already done. "
            "Continue from where you left off - do not redo completed work."
        )

    save_state(state)

    console.print("\n" + "=" * 60)
    console.print("[yellow]⏸️  TASK PAUSED[/yellow]")
    console.print("=" * 60)
    console.print(f"\nTask: {state.task_name}")
    console.print(f"Stage: {state.stage.value} (attempt {state.attempt})")
    console.print("\nYour progress has been saved. You can safely shut down now.")
    console.print("\nTo resume later, run:")
    console.print("  [cyan]galangal resume[/cyan]")
    console.print("=" * 60)
