"""
Console output utilities using Rich.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from galangal.core.state import TASK_TYPE_SKIP_STAGES, Stage, TaskType

console = Console()


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]✓ {message}[/green]")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[red]✗ {message}[/red]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]⚠ {message}[/yellow]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[blue]ℹ {message}[/blue]")


def display_task_list(
    tasks: list[tuple[str, str, str, str]], active: str | None
) -> None:
    """Display a table of tasks."""
    if not tasks:
        print_info("No tasks found.")
        return

    table = Table(title="Tasks")
    table.add_column("", style="cyan", width=2)
    table.add_column("Name", style="bold")
    table.add_column("Stage")
    table.add_column("Type")
    table.add_column("Description")

    for name, stage, task_type, desc in tasks:
        marker = "→" if name == active else ""
        stage_style = "green" if stage == "COMPLETE" else "yellow"
        table.add_row(
            marker,
            name,
            f"[{stage_style}]{stage}[/{stage_style}]",
            task_type,
            desc,
        )

    console.print(table)


def display_status(
    task_name: str,
    stage: Stage,
    task_type: TaskType,
    attempt: int,
    awaiting_approval: bool,
    last_failure: str | None,
    description: str,
    artifacts: list[tuple[str, bool]],
) -> None:
    """Display detailed task status."""
    status_color = "green" if stage == Stage.COMPLETE else "yellow"

    console.print(Panel(f"[bold]{task_name}[/bold]", title="Task Status"))
    console.print(f"[dim]Stage:[/dim] [{status_color}]{stage.value}[/{status_color}]")
    console.print(f"[dim]Type:[/dim] {task_type.display_name()}")
    console.print(f"[dim]Attempt:[/dim] {attempt}")
    console.print(f"[dim]Description:[/dim] {description[:100]}...")

    if awaiting_approval:
        console.print("[yellow]⏳ Awaiting approval[/yellow]")

    if last_failure:
        console.print(f"[red]Last failure:[/red] {last_failure[:200]}...")

    # Artifacts
    console.print("\n[bold]Artifacts:[/bold]")
    for name, exists in artifacts:
        icon = "✓" if exists else "○"
        color = "green" if exists else "dim"
        console.print(f"  [{color}]{icon} {name}[/{color}]")


def display_task_type_menu() -> None:
    """Display the task type selection menu."""
    console.print("\n[bold]Select task type:[/bold]")
    for i, task_type in enumerate(TaskType, 1):
        skipped = TASK_TYPE_SKIP_STAGES.get(task_type, set())
        skip_info = f" [dim](skips: {', '.join(s.value for s in skipped)})[/dim]" if skipped else ""
        console.print(f"  [{i}] {task_type.display_name()} - {task_type.description()}{skip_info}")


def get_task_type_from_input(choice: str) -> TaskType | None:
    """Convert user input to TaskType."""
    task_types = list(TaskType)

    # Try numeric selection
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(task_types):
            return task_types[idx]
    except ValueError:
        pass

    # Try name match
    choice_lower = choice.lower().replace(" ", "_").replace("-", "_")
    for tt in TaskType:
        if tt.value == choice_lower or tt.display_name().lower() == choice.lower():
            return tt

    return None
