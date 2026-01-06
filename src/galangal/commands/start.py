"""
galangal start - Start a new task.
"""

import argparse

from rich.prompt import Prompt

from galangal.config.loader import get_config
from galangal.core.state import (
    Stage,
    TaskType,
    WorkflowState,
    save_state,
    get_task_dir,
    TASK_TYPE_SKIP_STAGES,
)
from galangal.core.tasks import (
    generate_task_name,
    task_name_exists,
    set_active_task,
    create_task_branch,
)
from galangal.core.workflow import run_workflow
from galangal.ui.console import (
    console,
    print_success,
    print_error,
    print_warning,
    display_task_type_menu,
    get_task_type_from_input,
)


def select_task_type() -> TaskType:
    """Interactive task type selection."""
    display_task_type_menu()

    while True:
        choice = Prompt.ask("Select type [1-6]", default="1").strip()
        task_type = get_task_type_from_input(choice)
        if task_type:
            console.print(f"\n[green]✓ Task type:[/green] {task_type.display_name()}")

            # Show which stages will be skipped
            skipped = TASK_TYPE_SKIP_STAGES.get(task_type, set())
            if skipped:
                skip_names = [s.value for s in skipped]
                console.print(f"[dim]   Stages to skip: {', '.join(skip_names)}[/dim]")

            return task_type

        print_error(f"Invalid choice: '{choice}'. Enter 1-6 or type name.")


def prompt_for_description() -> str:
    """Prompt user for multi-line task description."""
    console.print(
        "\n[bold]Enter task description[/bold] (press Enter twice to finish):"
    )
    console.print("[dim]" + "-" * 40 + "[/dim]")
    lines = []
    empty_count = 0

    while True:
        try:
            line = input()
            if line == "":
                empty_count += 1
                if empty_count >= 2:
                    break
                lines.append(line)
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def cmd_start(args: argparse.Namespace) -> int:
    """Start a new task."""
    config = get_config()
    description = " ".join(args.description) if args.description else ""

    # Select task type first
    task_type = select_task_type()

    # Prompt for description if not provided
    if not description:
        description = prompt_for_description()
        if not description.strip():
            print_error("Task description required")
            return 1

    # Generate or use provided task name
    if args.name:
        task_name = args.name
        if task_name_exists(task_name):
            print_error(f"Task '{task_name}' already exists. Use a different name.")
            return 1
        task_dir = get_task_dir(task_name)
    else:
        console.print("[dim]Generating task name...[/dim]", end=" ")
        base_name = generate_task_name(description)
        task_name = base_name

        suffix = 2
        while task_name_exists(task_name):
            task_name = f"{base_name}-{suffix}"
            suffix += 1

        task_dir = get_task_dir(task_name)
        console.print(f"[cyan]{task_name}[/cyan]")

    # Create git branch
    success, msg = create_task_branch(task_name)
    if not success:
        print_warning(msg)
    else:
        print_success(msg)

    # Create task directory
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "logs").mkdir(exist_ok=True)

    # Initialize state with task type
    state = WorkflowState.new(description, task_name, task_type)
    save_state(state)

    # Set as active task
    set_active_task(task_name)

    console.print(f"\n[bold]Created task:[/bold] {task_name}")
    console.print(f"[dim]Location:[/dim] {config.tasks_dir}/{task_name}/")
    console.print(f"[dim]Type:[/dim] {task_type.display_name()}")
    console.print(f"[dim]Description:[/dim] {description[:60]}...")

    run_workflow(state)
    return 0
