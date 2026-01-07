"""
Pause handling for workflow execution.
"""

from rich.console import Console

from galangal.ai.claude import set_pause_requested
from galangal.core.state import WorkflowState, save_state

console = Console()

# Global state for pause handling
_current_state: WorkflowState | None = None


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGINT (Ctrl+C) gracefully."""
    set_pause_requested(True)
    console.print(
        "\n\n[yellow]⏸️  Pause requested - finishing current operation...[/yellow]"
    )
    console.print("[dim]   (Press Ctrl+C again to force quit)[/dim]\n")


def _handle_pause(state: WorkflowState) -> None:
    """Handle a pause request."""
    set_pause_requested(False)
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


def get_current_state() -> WorkflowState | None:
    """Get the current workflow state (for signal handlers)."""
    return _current_state


def set_current_state(state: WorkflowState | None) -> None:
    """Set the current workflow state (for signal handlers)."""
    global _current_state
    _current_state = state
