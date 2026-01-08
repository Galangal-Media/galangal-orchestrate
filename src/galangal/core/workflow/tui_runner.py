"""
TUI-based workflow runner using persistent Textual app.
"""

import threading

from rich.console import Console

from galangal.config.loader import get_config
from galangal.core.artifacts import artifact_exists, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    Stage,
    TaskType,
    WorkflowState,
    get_hidden_stages_for_task_type,
    save_state,
)
from galangal.core.workflow.core import (
    archive_rollback_if_exists,
    execute_stage,
    get_next_stage,
    handle_rollback,
)
from galangal.core.workflow.pause import _handle_pause
from galangal.results import StageResultType
from galangal.ui.tui import PromptType, WorkflowTUIApp

console = Console()


def _run_workflow_with_tui(state: WorkflowState) -> str:
    """Run workflow with persistent TUI. Returns result string."""
    config = get_config()
    max_retries = config.stages.max_retries

    # Compute hidden stages based on task type and config
    hidden_stages = frozenset(
        get_hidden_stages_for_task_type(state.task_type, config.stages.skip)
    )

    app = WorkflowTUIApp(
        state.task_name,
        state.stage.value,
        hidden_stages=hidden_stages,
    )

    # Shared state for thread communication
    workflow_done = threading.Event()

    def workflow_thread():
        """Run the workflow loop in a background thread."""
        try:
            while state.stage != Stage.COMPLETE and not app._paused:
                app.update_stage(state.stage.value, state.attempt)
                app.set_status("running", f"executing {state.stage.value}")

                # Execute stage with the TUI app
                # Pass pause_check callback so the backend can check for pause during execution
                result = execute_stage(state, tui_app=app, pause_check=lambda: app._paused)

                if app._paused:
                    app._workflow_result = "paused"
                    break

                if not result.success:
                    app.show_stage_complete(state.stage.value, False)

                    # Handle preflight failures specially - don't auto-retry
                    if result.type == StageResultType.PREFLIGHT_FAILED:
                        detailed_error = result.output or result.message

                        # Extract failed checks for display in modal
                        failed_lines = []
                        for line in detailed_error.split("\n"):
                            if (
                                line.strip().startswith("✗")
                                or "Failed" in line
                                or "Missing" in line
                                or "Error" in line
                            ):
                                failed_lines.append(line.strip())

                        # Build modal message with error details
                        modal_message = "Preflight checks failed:\n\n"
                        if failed_lines:
                            modal_message += "\n".join(failed_lines[:10])  # Limit to 10 lines
                        else:
                            modal_message += detailed_error[:500]
                        modal_message += "\n\nFix issues and retry?"

                        # Prompt user to retry after fixing
                        retry_event = threading.Event()
                        retry_result = {"value": None}

                        def handle_preflight_retry(choice):
                            retry_result["value"] = choice
                            retry_event.set()

                        app.show_prompt(
                            PromptType.PREFLIGHT_RETRY,
                            modal_message,
                            handle_preflight_retry,
                        )

                        retry_event.wait()
                        if retry_result["value"] == "retry":
                            app.show_message("Retrying preflight checks...", "info")
                            continue  # Retry without incrementing attempt
                        else:
                            save_state(state)
                            app._workflow_result = "paused"
                            break

                    # Handle clarification needed
                    if result.type == StageResultType.CLARIFICATION_NEEDED:
                        app.show_message(result.message, "warning")
                        save_state(state)
                        app._workflow_result = "paused"
                        break

                    # Handle rollback required
                    if result.type == StageResultType.ROLLBACK_REQUIRED:
                        if handle_rollback(state, result):
                            app.show_message(f"Rolling back: {result.message[:80]}", "warning")
                            continue

                    # Get error message for display
                    error_message = result.output or result.message

                    state.attempt += 1
                    state.last_failure = error_message

                    if state.attempt > max_retries:
                        # Build modal message with error details
                        error_preview = error_message[:800].strip()
                        if len(error_message) > 800:
                            error_preview += "..."

                        modal_message = (
                            f"Stage {state.stage.value} failed after {max_retries} attempts.\n\n"
                        )
                        modal_message += f"Error:\n{error_preview}\n\n"
                        modal_message += "What would you like to do?"

                        # Prompt user for what to do
                        failure_event = threading.Event()
                        failure_result = {"value": None, "feedback": None}

                        def handle_failure_choice(choice):
                            failure_result["value"] = choice
                            if choice == "fix_in_dev":
                                # Need to get feedback first
                                def handle_feedback(feedback):
                                    failure_result["feedback"] = feedback
                                    failure_event.set()

                                app.show_multiline_input(
                                    "Describe what needs to be fixed (Ctrl+S to submit):",
                                    "",
                                    handle_feedback,
                                )
                            else:
                                failure_event.set()

                        app.show_prompt(
                            PromptType.STAGE_FAILURE,
                            modal_message,
                            handle_failure_choice,
                        )

                        failure_event.wait()

                        if failure_result["value"] == "retry":
                            state.attempt = 1  # Reset attempts
                            app.show_message("Retrying stage...", "info")
                            save_state(state)
                            continue
                        elif failure_result["value"] == "fix_in_dev":
                            feedback = failure_result["feedback"] or "Fix the failing stage"
                            # Roll back to DEV with feedback
                            failing_stage = state.stage.value
                            state.stage = Stage.DEV
                            state.attempt = 1
                            state.last_failure = (
                                f"Feedback from {failing_stage} failure: {feedback}\n\n"
                                f"Original error:\n{error_message[:1500]}"
                            )
                            app.show_message("Rolling back to DEV with feedback", "warning")
                            save_state(state)
                            continue
                        else:
                            save_state(state)
                            app._workflow_result = "paused"
                            break

                    app.show_message(
                        f"Retrying (attempt {state.attempt}/{max_retries})...", "warning"
                    )
                    save_state(state)
                    continue

                app.show_stage_complete(state.stage.value, True)

                # Plan approval gate - handle in TUI with two-step flow
                if state.stage == Stage.PM and not artifact_exists("APPROVAL.md", state.task_name):
                    approval_event = threading.Event()
                    approval_result = {"value": None, "approver": None, "reason": None}

                    # Get default approver name from config
                    default_approver = config.project.approver_name or ""

                    def handle_approval(choice):
                        if choice == "yes":
                            approval_result["value"] = "pending_name"
                            # Don't set event yet - wait for name input
                        elif choice == "no":
                            approval_result["value"] = "pending_reason"
                            # Don't set event yet - wait for rejection reason
                        else:
                            approval_result["value"] = "quit"
                            approval_event.set()

                    def handle_approver_name(name):
                        if name:
                            approval_result["value"] = "approved"
                            approval_result["approver"] = name
                            # Write approval artifact with approver name
                            from datetime import datetime, timezone

                            approval_content = f"""# Plan Approval

- **Status:** Approved
- **Approved By:** {name}
- **Date:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
"""
                            write_artifact("APPROVAL.md", approval_content, state.task_name)
                            app.show_message(f"Plan approved by {name}", "success")
                        else:
                            # Cancelled - go back to approval prompt
                            approval_result["value"] = None
                            app.show_prompt(
                                PromptType.PLAN_APPROVAL, "Approve plan to continue?", handle_approval
                            )
                            return  # Don't set event - wait for new choice
                        approval_event.set()

                    def handle_rejection_reason(reason):
                        if reason:
                            approval_result["value"] = "rejected"
                            approval_result["reason"] = reason
                            state.stage = Stage.PM
                            state.attempt = 1
                            state.last_failure = f"Plan rejected: {reason}"
                            save_state(state)
                            app.show_message(f"Plan rejected: {reason}", "warning")
                        else:
                            # Cancelled - go back to approval prompt
                            approval_result["value"] = None
                            app.show_prompt(
                                PromptType.PLAN_APPROVAL, "Approve plan to continue?", handle_approval
                            )
                            return  # Don't set event - wait for new choice
                        approval_event.set()

                    app.show_prompt(
                        PromptType.PLAN_APPROVAL, "Approve plan to continue?", handle_approval
                    )

                    # Wait for choice, then potentially for name or reason
                    while not approval_event.is_set():
                        approval_event.wait(timeout=0.1)
                        if approval_result["value"] == "pending_name":
                            approval_result["value"] = None  # Reset
                            app.show_text_input(
                                "Enter approver name:", default_approver, handle_approver_name
                            )
                        elif approval_result["value"] == "pending_reason":
                            approval_result["value"] = None  # Reset
                            app.show_multiline_input(
                                "Enter rejection reason (Ctrl+S to submit):", "Needs revision", handle_rejection_reason
                            )

                    if approval_result["value"] == "quit":
                        app._workflow_result = "paused"
                        break
                    elif approval_result["value"] == "rejected":
                        app.show_message("Restarting PM stage with feedback...", "info")
                        continue

                if state.stage == Stage.DEV:
                    archive_rollback_if_exists(state.task_name, app)

                # Get next stage
                next_stage = get_next_stage(state.stage, state)
                if next_stage:
                    expected_next_idx = STAGE_ORDER.index(state.stage) + 1
                    actual_next_idx = STAGE_ORDER.index(next_stage)
                    if actual_next_idx > expected_next_idx:
                        skipped = STAGE_ORDER[expected_next_idx:actual_next_idx]
                        for s in skipped:
                            app.show_message(f"Skipped {s.value} (condition not met)", "info")

                    state.stage = next_stage
                    state.attempt = 1
                    state.last_failure = None
                    state.awaiting_approval = False
                    state.clarification_required = False
                    save_state(state)
                else:
                    state.stage = Stage.COMPLETE
                    save_state(state)

            # Workflow complete
            if state.stage == Stage.COMPLETE:
                app.show_workflow_complete()
                app.update_stage("COMPLETE")
                app.set_status("complete", "workflow finished")

                completion_event = threading.Event()
                completion_result = {"value": None}

                def handle_completion(choice):
                    completion_result["value"] = choice
                    completion_event.set()

                app.show_prompt(PromptType.COMPLETION, "Workflow complete!", handle_completion)
                completion_event.wait()

                if completion_result["value"] == "yes":
                    # Run finalization within TUI
                    app.set_status("finalizing", "creating PR...")

                    def progress_callback(message, status):
                        app.show_message(message, status)

                    from galangal.commands.complete import finalize_task

                    success, pr_url = finalize_task(
                        state.task_name, state, force=True, progress_callback=progress_callback
                    )

                    if success:
                        app.add_activity("")
                        app.add_activity("[bold #b8bb26]Task completed successfully![/]", "✓")
                        if pr_url and pr_url != "PR already exists":
                            app.add_activity(f"[#83a598]PR: {pr_url}[/]", "")
                        app.add_activity("")

                    # Show post-completion options with PR URL
                    post_event = threading.Event()
                    post_result = {"value": None}

                    def handle_post_completion(choice):
                        post_result["value"] = choice
                        post_event.set()

                    # Build completion message with PR URL if available
                    completion_msg = "Task completed successfully!"
                    if pr_url and pr_url.startswith("http"):
                        completion_msg += f"\n\nPull Request:\n{pr_url}"
                    completion_msg += "\n\nWhat would you like to do next?"

                    app.show_prompt(
                        PromptType.POST_COMPLETION,
                        completion_msg,
                        handle_post_completion,
                    )
                    post_event.wait()

                    if post_result["value"] == "new_task":
                        app._workflow_result = "new_task"
                    else:
                        app._workflow_result = "done"
                elif completion_result["value"] == "no":
                    # Ask for feedback about what needs fixing
                    app.set_status("feedback", "waiting for input")
                    feedback_event = threading.Event()
                    feedback_result = {"value": None}

                    def handle_feedback(text):
                        feedback_result["value"] = text
                        feedback_event.set()

                    app.show_multiline_input(
                        "What needs to be fixed? (Ctrl+S to submit):",
                        "",
                        handle_feedback,
                    )
                    feedback_event.wait()

                    feedback = feedback_result["value"]
                    if feedback:
                        # Create ROLLBACK.md with the feedback
                        from datetime import datetime, timezone

                        rollback_content = f"""# Manual Review Rollback

## Source
Manual review at COMPLETE stage

## Date
{datetime.now(timezone.utc).isoformat()}

## Issues to Fix
{feedback}

## Instructions
Please address the issues described above before proceeding.
"""
                        write_artifact("ROLLBACK.md", rollback_content, state.task_name)
                        state.last_failure = f"Manual review feedback: {feedback}"
                        app.show_message("Feedback recorded, rolling back to DEV", "warning")
                    else:
                        state.last_failure = "Manual review requested changes (no details provided)"
                        app.show_message("Rolling back to DEV (no feedback provided)", "warning")

                    state.stage = Stage.DEV
                    state.attempt = 1
                    save_state(state)
                    app._workflow_result = "back_to_dev"
                else:
                    app._workflow_result = "paused"

        except Exception as e:
            app.show_message(f"Error: {e}", "error")
            app._workflow_result = "error"
        finally:
            workflow_done.set()
            app.call_from_thread(app.set_timer, 0.5, app.exit)

    # Start workflow in background thread
    thread = threading.Thread(target=workflow_thread, daemon=True)

    def start_thread():
        thread.start()

    app.call_later(start_thread)
    app.run()

    # Handle result
    result = app._workflow_result or "paused"

    if result == "new_task":
        # Start new task flow - prompt for task type and description
        return _start_new_task_tui()
    elif result == "done":
        # Clean exit after successful completion
        console.print("\n[green]✓ All done![/green]")
        return result
    elif result == "back_to_dev":
        # Restart workflow from DEV
        return _run_workflow_with_tui(state)
    elif result == "paused":
        _handle_pause(state)

    return result


def _start_new_task_tui() -> str:
    """Start a new task with TUI prompts for type and description."""
    # Create a minimal TUI app for task creation
    app = WorkflowTUIApp("New Task", "SETUP", hidden_stages=frozenset())

    task_info = {"type": None, "description": None, "name": None}
    creation_done = threading.Event()

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

            # Show task type selection (we have 3 options in the modal, offer more via text)
            app.show_prompt(
                PromptType.TASK_TYPE,
                "Select task type:",
                handle_type,
            )
            type_event.wait()

            if type_result["value"] == "quit":
                app._workflow_result = "cancelled"
                creation_done.set()
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

            # Step 2: Get task description
            app.set_status("setup", "enter description")
            desc_event = threading.Event()

            def handle_description(desc):
                task_info["description"] = desc
                desc_event.set()

            app.show_multiline_input("Enter task description (Ctrl+S to submit):", "", handle_description)
            desc_event.wait()

            if not task_info["description"]:
                app.show_message("Task creation cancelled", "warning")
                app._workflow_result = "cancelled"
                creation_done.set()
                app.call_from_thread(app.set_timer, 0.5, app.exit)
                return

            # Step 3: Generate and confirm task name
            app.set_status("setup", "generating task name")
            from galangal.commands.start import create_task, generate_task_name

            task_name = generate_task_name(task_info["description"])
            task_info["name"] = task_name
            app.show_message(f"Task name: {task_name}", "info")

            # Create the task
            app.set_status("setup", "creating task")
            success, message = create_task(
                task_name,
                task_info["description"],
                task_info["type"],
            )

            if success:
                app.show_message(message, "success")
                app._workflow_result = "task_created"
            else:
                app.show_message(f"Failed: {message}", "error")
                app._workflow_result = "error"

        except Exception as e:
            app.show_message(f"Error: {e}", "error")
            app._workflow_result = "error"
        finally:
            creation_done.set()
            app.call_from_thread(app.set_timer, 0.5, app.exit)

    # Start creation in background thread
    thread = threading.Thread(target=task_creation_thread, daemon=True)
    app.call_later(thread.start)
    app.run()

    result = app._workflow_result or "cancelled"

    if result == "task_created" and task_info["name"]:
        # Load new state and start workflow
        from galangal.core.state import load_state

        new_state = load_state(task_info["name"])
        if new_state:
            return _run_workflow_with_tui(new_state)

    return result
