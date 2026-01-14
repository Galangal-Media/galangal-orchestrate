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
    generate_unique_task_name,
    set_active_task,
    task_name_exists,
)
from galangal.core.utils import debug_exception, debug_log
from galangal.core.workflow import run_workflow
from galangal.ui.tui import PromptType, WorkflowTUIApp


def create_task(
    task_name: str,
    description: str,
    task_type: TaskType,
    github_issue: int | None = None,
    github_repo: str | None = None,
    screenshots: list[str] | None = None,
) -> tuple[bool, str]:
    """Create a new task with the given name, description, and type.

    Args:
        task_name: Name for the task (will be used for directory and branch)
        description: Task description
        task_type: Type of task (Feature, Bug Fix, etc.)
        github_issue: Optional GitHub issue number this task is linked to
        github_repo: Optional GitHub repo (owner/repo) for the issue
        screenshots: Optional list of local screenshot paths from the issue

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

    # Initialize state with task type and optional GitHub info
    state = WorkflowState.new(
        description, task_name, task_type, github_issue, github_repo, screenshots
    )
    save_state(state)

    # Set as active task
    set_active_task(task_name)

    return True, f"Created task: {task_name}"


def cmd_start(args: argparse.Namespace) -> int:
    """Start a new task."""
    from galangal.config.loader import is_initialized
    from galangal.ui.console import print_error, print_info

    # Check if project is initialized
    if not is_initialized():
        print_error("Galangal has not been initialized in this project.")
        print_info("Run 'galangal init' first to set up your project.")
        return 1

    description = " ".join(args.description) if args.description else ""
    task_name = args.name or ""
    from_issue = getattr(args, "issue", None)

    # Create TUI app for task setup
    app = WorkflowTUIApp("New Task", "SETUP", hidden_stages=frozenset())

    task_info = {
        "type": None,
        "description": description,
        "name": task_name,
        "github_issue": from_issue,
        "github_repo": None,
        "screenshots": None,
    }
    result_code = {"value": 0}

    def task_creation_thread():
        try:
            app.add_activity("[bold]Starting new task...[/bold]", "🆕")

            # Step 0: Choose task source (manual or GitHub) if no description/issue provided
            if not task_info["description"] and not task_info["github_issue"]:
                app.set_status("setup", "select task source")

                source_event = threading.Event()
                source_result = {"value": None}

                def handle_source(choice):
                    source_result["value"] = choice
                    source_event.set()

                app.show_prompt(
                    PromptType.TASK_SOURCE,
                    "Create task from:",
                    handle_source,
                )
                source_event.wait()

                if source_result["value"] == "quit":
                    app._workflow_result = "cancelled"
                    result_code["value"] = 1
                    app.call_from_thread(app.set_timer, 0.5, app.exit)
                    return

                if source_result["value"] == "github":
                    # Handle GitHub issue selection
                    app.set_status("setup", "checking GitHub")
                    app.show_message("Checking GitHub setup...", "info")

                    try:
                        from galangal.github.client import ensure_github_ready
                        from galangal.github.issues import list_issues

                        check = ensure_github_ready()
                        if not check:
                            app.show_message(
                                "GitHub not ready. Run 'galangal github check'",
                                "error"
                            )
                            app._workflow_result = "error"
                            result_code["value"] = 1
                            app.call_from_thread(app.set_timer, 0.5, app.exit)
                            return

                        task_info["github_repo"] = check.repo_name

                        # List issues with galangal label
                        app.set_status("setup", "fetching issues")
                        app.show_message("Fetching issues...", "info")

                        issues = list_issues()
                        if not issues:
                            app.show_message("No issues with 'galangal' label found", "warning")
                            app._workflow_result = "cancelled"
                            result_code["value"] = 1
                            app.call_from_thread(app.set_timer, 0.5, app.exit)
                            return

                        # Show issue selection
                        app.set_status("setup", "select issue")
                        issue_event = threading.Event()
                        issue_result = {"value": None}

                        def handle_issue(issue_num):
                            issue_result["value"] = issue_num
                            issue_event.set()

                        issue_options = [(i.number, i.title) for i in issues]
                        app.show_github_issue_select(issue_options, handle_issue)
                        issue_event.wait()

                        if issue_result["value"] is None:
                            app._workflow_result = "cancelled"
                            result_code["value"] = 1
                            app.call_from_thread(app.set_timer, 0.5, app.exit)
                            return

                        # Get the selected issue details
                        selected_issue = next(
                            (i for i in issues if i.number == issue_result["value"]),
                            None
                        )
                        if selected_issue:
                            task_info["github_issue"] = selected_issue.number
                            task_info["description"] = (
                                f"{selected_issue.title}\n\n{selected_issue.body}"
                            )
                            app.show_message(
                                f"Selected issue #{selected_issue.number}",
                                "success"
                            )

                            # Download screenshots from issue body
                            from galangal.github.images import extract_image_urls
                            images = extract_image_urls(selected_issue.body)
                            if images:
                                app.set_status("setup", "downloading screenshots")
                                app.show_message(
                                    f"Found {len(images)} screenshot(s) in issue...",
                                    "info"
                                )
                                # Note: Actual download happens after task_name is generated
                                # Store the issue body for later processing
                                task_info["_issue_body"] = selected_issue.body

                            # Try to infer task type from labels
                            type_hint = selected_issue.get_task_type_hint()
                            if type_hint:
                                task_info["type"] = TaskType.from_str(type_hint)
                                app.show_message(
                                    f"Inferred type from labels: {task_info['type'].display_name()}",
                                    "info"
                                )

                    except Exception as e:
                        debug_exception("GitHub integration failed", e)
                        app.show_message(f"GitHub error: {e}", "error")
                        app._workflow_result = "error"
                        result_code["value"] = 1
                        app.call_from_thread(app.set_timer, 0.5, app.exit)
                        return

            # Step 1: Get task type (if not already set from GitHub labels)
            if task_info["type"] is None:
                app.set_status("setup", "select task type")

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
                task_info["type"] = TaskType.from_str(type_result["value"])

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

                # Use prefix for GitHub issues
                prefix = f"issue-{task_info['github_issue']}" if task_info["github_issue"] else None
                task_info["name"] = generate_unique_task_name(task_info["description"], prefix)
            else:
                # Validate provided name
                if task_name_exists(task_info["name"]):
                    app.show_message(f"Task '{task_info['name']}' already exists", "error")
                    app._workflow_result = "cancelled"
                    result_code["value"] = 1
                    app.call_from_thread(app.set_timer, 0.5, app.exit)
                    return

            app.show_message(f"Task name: {task_info['name']}", "success")
            debug_log("Task name generated", name=task_info["name"])

            # Step 4: Create the task (must happen BEFORE screenshot download
            # because download_issue_screenshots creates the task directory)
            app.set_status("setup", "creating task")
            debug_log("Creating task", name=task_info["name"], type=str(task_info["type"]))
            success, message = create_task(
                task_info["name"],
                task_info["description"],
                task_info["type"],
                github_issue=task_info["github_issue"],
                github_repo=task_info["github_repo"],
            )

            if success:
                app.show_message(message, "success")
                app._workflow_result = "task_created"
                debug_log("Task created successfully", name=task_info["name"])

                # Step 4.5: Download screenshots if from GitHub issue
                # (must happen AFTER task creation since it writes to task directory)
                if task_info.get("_issue_body"):
                    app.set_status("setup", "downloading screenshots")
                    issue_body = task_info["_issue_body"]
                    debug_log(
                        "Starting screenshot download",
                        body_length=len(issue_body),
                        body_preview=issue_body[:200] if issue_body else "empty",
                    )
                    try:
                        from galangal.github.issues import download_issue_screenshots

                        task_dir = get_task_dir(task_info["name"])
                        screenshot_paths = download_issue_screenshots(
                            task_info["_issue_body"],
                            task_dir,
                        )
                        if screenshot_paths:
                            task_info["screenshots"] = screenshot_paths
                            app.show_message(
                                f"Downloaded {len(screenshot_paths)} screenshot(s)",
                                "success"
                            )
                            debug_log("Screenshots downloaded", count=len(screenshot_paths))

                            # Update state with screenshot paths
                            state = load_state(task_info["name"])
                            if state:
                                state.screenshots = screenshot_paths
                                save_state(state)
                    except Exception as e:
                        debug_exception("Screenshot download failed", e)
                        app.show_message(f"Screenshot download failed: {e}", "warning")
                        # Non-critical - continue without screenshots

                # Mark issue as in-progress if from GitHub
                if task_info["github_issue"]:
                    try:
                        from galangal.github.issues import mark_issue_in_progress
                        mark_issue_in_progress(task_info["github_issue"])
                        app.show_message("Marked issue as in-progress", "info")
                    except Exception as e:
                        debug_exception("Failed to mark issue as in-progress", e)
                        # Non-critical - continue anyway
            else:
                app.show_message(f"Failed: {message}", "error")
                app._workflow_result = "error"
                result_code["value"] = 1

        except Exception as e:
            debug_exception("Task creation failed", e)
            app.show_message(f"Error: {e}", "error")
            app._workflow_result = "error"
            result_code["value"] = 1
        finally:
            app.call_from_thread(app.set_timer, 0.5, app.exit)

    # Start creation in background thread
    thread = threading.Thread(target=task_creation_thread, daemon=True)
    app.call_later(thread.start)
    app.run()

    # Log the TUI result for debugging
    debug_log(
        "TUI app exited",
        result=getattr(app, '_workflow_result', 'unknown'),
        task_name=task_info.get("name", "none"),
        result_code=result_code["value"],
    )

    # If task was created, start the workflow
    if app._workflow_result == "task_created" and task_info["name"]:
        debug_log("Task created, loading state", task=task_info["name"])
        state = load_state(task_info["name"])
        if state:
            # Pass skip_discovery flag via state attribute
            if getattr(args, 'skip_discovery', False):
                state._skip_discovery = True
            try:
                debug_log("Starting workflow", task=task_info["name"])
                run_workflow(state)
            except Exception as e:
                debug_exception("Workflow failed to start", e)
                from galangal.ui.console import print_error
                print_error(f"Workflow failed: {e}")
                return 1
        else:
            debug_log("Failed to load state", task=task_info["name"])
    else:
        debug_log(
            "Not starting workflow",
            reason=f"result={getattr(app, '_workflow_result', 'unknown')}, name={task_info.get('name', 'none')}",
        )

    return result_code["value"]
