"""
galangal start - Start a new task.
"""

import argparse
import threading

from galangal.core.state import (
    TaskType,
    WorkflowState,
    get_task_dir,
    load_state,
    save_state,
)
from galangal.core.tasks import (
    create_task_branch,
    generate_task_name,
    set_active_task,
    task_name_exists,
)
from galangal.core.workflow import run_workflow
from galangal.ui.tui import PromptType, WorkflowTUIApp


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


def cmd_start(args: argparse.Namespace) -> int:
    """Start a new task."""
    description = " ".join(args.description) if args.description else ""
    task_name = args.name or ""

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

                app.show_multiline_input("Enter task description (Ctrl+S to submit):", "", handle_description)
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
