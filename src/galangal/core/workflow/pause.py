"""
Pause handling for workflow execution.
"""

from rich.console import Console

from galangal.core.state import WorkflowState, save_state

console = Console()


def _handle_pause(state: WorkflowState) -> None:
    """Handle a pause request. Called after TUI exits."""
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
