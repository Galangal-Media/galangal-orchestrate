"""
galangal start - Start a new task.
"""

import argparse

from rich.prompt import Prompt

from galangal.config.loader import get_config
from galangal.core.state import (
    TASK_TYPE_SKIP_STAGES,
    TaskType,
    WorkflowState,
    get_task_dir,
    save_state,
)
from galangal.core.tasks import (
    create_task_branch,
    generate_task_name,
    set_active_task,
    task_name_exists,
)
from galangal.core.workflow import run_workflow
from galangal.ui.console import (
    console,
    display_task_type_menu,
    get_task_type_from_input,
    print_error,
    print_success,
    print_warning,
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


def create_task(task_name: str, description: str, task_type: TaskType) -> tuple[bool, str]:
    """Create a new task with the given name, description, and type.

    Args:
        task_name: Name for the task (will be used for directory and branch)
        description: Task description
        task_type: Type of task (Feature, Bug Fix, etc.)

    Returns:
        Tuple of (success, message)
    """
    # Check if task already exists
    if task_name_exists(task_name):
        return False, f"Task '{task_name}' already exists"

    task_dir = get_task_dir(task_name)

    # Create git branch
    success, msg = create_task_branch(task_name)
    if not success and "already exists" not in msg.lower():
        return False, msg

    # Create task directory
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "logs").mkdir(exist_ok=True)

    # Initialize state with task type
    state = WorkflowState.new(description, task_name, task_type)
    save_state(state)

    # Set as active task
    set_active_task(task_name)

    return True, f"Created task: {task_name}"


def _start_task_with_tui(
    description: str = "",
    task_name: str = "",
) -> int:
    """Start a new task using TUI for all prompts."""
    import threading

    from galangal.core.state import load_state
    from galangal.ui.tui import PromptType, WorkflowTUIApp

    # Create TUI app for task setup
    app = WorkflowTUIApp("New Task", "SETUP", hidden_stages=frozenset())

    task_info = {"type": None, "description": description, "name": task_name}
    result_code = {"value": 0}

    def task_creation_thread():
        try:
            app.add_activity("[bold]Starting new task...[/bold]", "🆕")
            app.set_status("setup", "select task type")

            # Step 1: Get task type
            type_event = threading.Event()
            type_result = {"value": None}

            def handle_type(choice):
                type_result["value"] = choice
                type_event.set()

            app.show_prompt(
                PromptType.TASK_TYPE,
                "Select task type:",
                handle_type,
            )
            type_event.wait()

            if type_result["value"] == "quit":
                app._workflow_result = "cancelled"
                result_code["value"] = 1
                app.call_from_thread(app.set_timer, 0.5, app.exit)
                return

            # Map selection to TaskType
            type_map = {
                "feature": TaskType.FEATURE,
                "bugfix": TaskType.BUG_FIX,
                "refactor": TaskType.REFACTOR,
                "chore": TaskType.CHORE,
                "docs": TaskType.DOCS,
                "hotfix": TaskType.HOTFIX,
            }
            task_info["type"] = type_map.get(type_result["value"], TaskType.FEATURE)
            app.show_message(f"Task type: {task_info['type'].display_name()}", "success")

            # Step 2: Get task description if not provided
            if not task_info["description"]:
                app.set_status("setup", "enter description")
                desc_event = threading.Event()

                def handle_description(desc):
                    task_info["description"] = desc
                    desc_event.set()

                app.show_text_input("Enter task description:", "", handle_description)
                desc_event.wait()

                if not task_info["description"]:
                    app.show_message("Task description required", "error")
                    app._workflow_result = "cancelled"
                    result_code["value"] = 1
                    app.call_from_thread(app.set_timer, 0.5, app.exit)
                    return

            # Step 3: Generate task name if not provided
            if not task_info["name"]:
                app.set_status("setup", "generating task name")
                app.show_message("Generating task name...", "info")

                base_name = generate_task_name(task_info["description"])
                final_name = base_name

                suffix = 2
                while task_name_exists(final_name):
                    final_name = f"{base_name}-{suffix}"
                    suffix += 1

                task_info["name"] = final_name
            else:
                # Validate provided name
                if task_name_exists(task_info["name"]):
                    app.show_message(f"Task '{task_info['name']}' already exists", "error")
                    app._workflow_result = "cancelled"
                    result_code["value"] = 1
                    app.call_from_thread(app.set_timer, 0.5, app.exit)
                    return

            app.show_message(f"Task name: {task_info['name']}", "success")

            # Step 4: Create the task
            app.set_status("setup", "creating task")
            success, message = create_task(
                task_info["name"],
                task_info["description"],
                task_info["type"],
            )

            if success:
                app.show_message(message, "success")
                app._workflow_result = "task_created"
            else:
                app.show_message(f"Failed: {message}", "error")
                app._workflow_result = "error"
                result_code["value"] = 1

        except Exception as e:
            app.show_message(f"Error: {e}", "error")
            app._workflow_result = "error"
            result_code["value"] = 1
        finally:
            app.call_from_thread(app.set_timer, 0.5, app.exit)

    # Start creation in background thread
    thread = threading.Thread(target=task_creation_thread, daemon=True)
    app.call_later(thread.start)
    app.run()

    # If task was created, start the workflow
    if app._workflow_result == "task_created" and task_info["name"]:
        state = load_state(task_info["name"])
        if state:
            run_workflow(state)

    return result_code["value"]


def cmd_start(args: argparse.Namespace) -> int:
    """Start a new task."""
    import os

    description = " ".join(args.description) if args.description else ""
    task_name = args.name or ""

    # Use TUI unless disabled
    if not os.environ.get("GALANGAL_NO_TUI"):
        try:
            return _start_task_with_tui(description, task_name)
        except Exception as e:
            console.print(f"[yellow]TUI error: {e}. Using legacy mode.[/yellow]")

    # Legacy console mode
    config = get_config()

    # Select task type first
    task_type = select_task_type()

    # Prompt for description if not provided
    if not description:
        description = prompt_for_description()
        if not description.strip():
            print_error("Task description required")
            return 1

    # Generate or use provided task name
    if task_name:
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
