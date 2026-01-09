"""
TUI-based workflow runner using persistent Textual app with async/await.

This module uses Textual's async capabilities for cleaner coordination
between UI events and workflow logic, eliminating manual threading.Event
coordination in favor of asyncio.Future-based prompts.
"""

import asyncio

from rich.console import Console

from galangal.config.loader import get_config
from galangal.core.artifacts import artifact_exists, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    Stage,
    TaskType,
    WorkflowState,
    get_hidden_stages_for_task_type,
    get_task_dir,
    save_state,
)
from galangal.core.workflow.core import (
    archive_rollback_if_exists,
    execute_stage,
    get_next_stage,
    handle_rollback,
)
from galangal.core.workflow.pause import _handle_pause
from galangal.prompts.builder import PromptBuilder
from galangal.results import StageResultType
from galangal.ui.tui import PromptType, WorkflowTUIApp

console = Console()


def _run_workflow_with_tui(state: WorkflowState) -> str:
    """
    Execute the workflow loop with a persistent Textual TUI.

    This is the main entry point for running workflows interactively. It creates
    a WorkflowTUIApp and runs the stage pipeline using async/await for clean
    coordination between UI and workflow logic.

    Threading Model (Async):
        - Main thread: Runs the Textual TUI event loop
        - Async worker: Executes workflow logic using Textual's run_worker()
        - Blocking operations (execute_stage) run in thread executor

    Args:
        state: Current workflow state containing task info, current stage,
            attempt count, and failure information.

    Returns:
        Result string indicating outcome:
        - "done": Workflow completed successfully and user chose to exit
        - "new_task": User chose to create a new task after completion
        - "paused": Workflow was paused (Ctrl+C or user quit)
        - "back_to_dev": User requested changes at completion, rolling back
        - "error": An exception occurred during execution
    """
    config = get_config()

    # Compute hidden stages based on task type and config
    hidden_stages = frozenset(
        get_hidden_stages_for_task_type(state.task_type, config.stages.skip)
    )

    app = WorkflowTUIApp(
        state.task_name,
        state.stage.value,
        hidden_stages=hidden_stages,
    )

    async def workflow_loop():
        """Async workflow loop running within Textual's event loop."""
        max_retries = config.stages.max_retries

        try:
            while state.stage != Stage.COMPLETE and not app._paused:
                app.update_stage(state.stage.value, state.attempt)
                app.set_status("running", f"executing {state.stage.value}")

                # Run PM discovery Q&A before PM stage execution
                if state.stage == Stage.PM and not state.qa_complete:
                    # Check for skip flag (passed via state or config)
                    skip_discovery = getattr(state, '_skip_discovery', False)
                    discovery_ok = await _run_pm_discovery(app, state, skip_discovery)
                    if not discovery_ok:
                        app._workflow_result = "paused"
                        break
                    app.set_status("running", f"executing {state.stage.value}")

                # Execute stage in thread executor (blocking operation)
                result = await asyncio.to_thread(
                    execute_stage,
                    state,
                    tui_app=app,
                    pause_check=lambda: app._paused,
                )

                if app._paused:
                    app._workflow_result = "paused"
                    break

                if not result.success:
                    app.show_stage_complete(state.stage.value, False)

                    # Handle preflight failures - prompt for retry
                    if result.type == StageResultType.PREFLIGHT_FAILED:
                        modal_message = _build_preflight_error_message(result)
                        choice = await app.prompt_async(
                            PromptType.PREFLIGHT_RETRY, modal_message
                        )

                        if choice == "retry":
                            app.show_message("Retrying preflight checks...", "info")
                            continue
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
                        target = result.rollback_to.value if result.rollback_to else 'None'
                        app.add_activity(
                            f"Validation requested rollback to {target}",
                            "⚠"
                        )
                        if handle_rollback(state, result):
                            app.show_message(
                                f"Rolling back to {state.stage.value}: {result.message[:60]}", "warning"
                            )
                            app.update_stage(state.stage.value, state.attempt)
                            continue
                        else:
                            # Rollback was blocked - prompt user for action
                            # This happens when: rollback loop detected, or rollback_to was None
                            rollback_count = state.get_rollback_count(result.rollback_to) if result.rollback_to else 0
                            if rollback_count >= 3:
                                block_reason = f"Too many rollbacks to {target} ({rollback_count} in last hour)"
                            elif result.rollback_to is None:
                                block_reason = "Rollback target not specified in validation"
                            else:
                                block_reason = "Rollback blocked (unknown reason)"

                            app.add_activity(f"Rollback blocked: {block_reason}", "⚠")
                            app.show_error(
                                f"Rollback blocked: {block_reason}",
                                result.message[:500],
                            )

                            # Prompt user for what to do
                            choice = await app.prompt_async(
                                PromptType.STAGE_FAILURE,
                                f"Rollback to {target} was blocked.\n\n"
                                f"Reason: {block_reason}\n\n"
                                f"Error: {result.message[:300]}\n\n"
                                "What would you like to do?"
                            )
                            app.clear_error()

                            if choice == "retry":
                                state.reset_attempts()
                                app.show_message("Retrying stage...", "info")
                                save_state(state)
                                continue
                            elif choice == "fix_in_dev":
                                # Force rollback to DEV by clearing rollback history for DEV
                                state.rollback_history = [
                                    r for r in state.rollback_history
                                    if r.to_stage != Stage.DEV.value
                                ]
                                state.stage = Stage.DEV
                                state.last_failure = f"Manual rollback from {state.stage.value}: {result.message[:500]}"
                                state.reset_attempts(clear_failure=False)
                                save_state(state)
                                app.show_message("Rolling back to DEV (manual override)", "warning")
                                app.update_stage(state.stage.value, state.attempt)
                                continue
                            else:
                                save_state(state)
                                app._workflow_result = "paused"
                                break
                    else:
                        # Log what result type we got (for debugging)
                        app.add_activity(
                            f"Validation result type: {result.type.name}",
                            "⚙"
                        )

                    # Handle stage failure with retries
                    error_message = result.output or result.message
                    state.record_failure(error_message)

                    if not state.can_retry(max_retries):
                        # Max retries exceeded - prompt user
                        choice = await _handle_max_retries_exceeded(
                            app, state, error_message, max_retries
                        )

                        if choice == "retry":
                            state.reset_attempts()
                            app.show_message("Retrying stage...", "info")
                            save_state(state)
                            continue
                        elif choice == "fix_in_dev":
                            # Handled in _handle_max_retries_exceeded
                            continue
                        else:
                            save_state(state)
                            app._workflow_result = "paused"
                            break

                    app.show_message(
                        f"Retrying (attempt {state.attempt}/{max_retries})...",
                        "warning",
                    )
                    save_state(state)
                    continue

                # Stage succeeded
                app.clear_error()  # Clear any previous error display
                app.show_stage_complete(state.stage.value, True)

                # Plan approval gate
                if state.stage == Stage.PM and not artifact_exists(
                    "APPROVAL.md", state.task_name
                ):
                    should_continue = await _handle_plan_approval(app, state, config)
                    if not should_continue:
                        if app._workflow_result == "paused":
                            break
                        continue  # Rejected - loop back to PM

                # Archive rollback after successful DEV
                if state.stage == Stage.DEV:
                    archive_rollback_if_exists(state.task_name, app)

                # Advance to next stage
                next_stage = get_next_stage(state.stage, state)
                if next_stage:
                    _show_skipped_stages(app, state.stage, next_stage)
                    state.stage = next_stage
                    state.reset_attempts()
                    state.awaiting_approval = False
                    state.clarification_required = False
                    save_state(state)
                else:
                    state.stage = Stage.COMPLETE
                    save_state(state)

            # Workflow complete
            if state.stage == Stage.COMPLETE:
                await _handle_workflow_complete(app, state)

        except Exception as e:
            app.show_error("Workflow error", str(e))
            app._workflow_result = "error"
        finally:
            app.set_timer(0.5, app.exit)

    # Start workflow as async worker
    app.call_later(lambda: app.run_worker(workflow_loop(), exclusive=True))
    app.run()

    # Handle result
    result = app._workflow_result or "paused"

    if result == "new_task":
        return _start_new_task_tui()
    elif result == "done":
        console.print("\n[green]✓ All done![/green]")
        return result
    elif result == "back_to_dev":
        return _run_workflow_with_tui(state)
    elif result == "paused":
        _handle_pause(state)

    return result


# -----------------------------------------------------------------------------
# PM Discovery Q&A functions
# -----------------------------------------------------------------------------


async def _run_pm_discovery(
    app: WorkflowTUIApp,
    state: WorkflowState,
    skip_discovery: bool = False,
) -> bool:
    """
    Run the PM discovery Q&A loop to refine the brief.

    This function handles the interactive Q&A process before PM stage execution:
    1. Generate clarifying questions from the AI
    2. Present questions to user via TUI
    3. Collect answers
    4. Loop until user is satisfied
    5. Write DISCOVERY_LOG.md artifact

    Args:
        app: TUI application for user interaction.
        state: Current workflow state to update with Q&A progress.
        skip_discovery: If True, skip the Q&A loop entirely.

    Returns:
        True if discovery completed (or was skipped), False if user cancelled/quit.
    """
    # Check if discovery should be skipped
    if skip_discovery or state.qa_complete:
        if state.qa_complete:
            app.show_message("Discovery Q&A already completed", "info")
        return True

    # Check if task type should skip discovery
    config = get_config()
    task_type_settings = config.task_type_settings.get(state.task_type.value)
    if task_type_settings and task_type_settings.skip_discovery:
        app.show_message(f"Discovery skipped for {state.task_type.display_name()} tasks", "info")
        state.qa_complete = True
        save_state(state)
        return True

    app.show_message("Starting brief discovery Q&A...", "info")
    app.set_status("discovery", "refining brief")

    qa_rounds: list[dict] = state.qa_rounds or []
    builder = PromptBuilder()

    while True:
        # Generate questions
        app.add_activity("Analyzing brief for clarifying questions...", "🔍")
        questions = await _generate_discovery_questions(app, state, builder, qa_rounds)

        if questions is None:
            # AI invocation failed
            app.show_message("Failed to generate questions", "error")
            return False

        if not questions:
            # AI found no gaps - ask user if they have questions
            continue_qa = await app.ask_yes_no_async(
                "AI found no gaps in the brief. Do you have your own questions to ask?"
            )
            if not continue_qa:
                break

            # Let user enter their own questions
            user_questions = await app.get_user_questions_async()
            if not user_questions:
                break
            questions = user_questions

        # Present questions and collect answers
        app.add_activity(f"Asking {len(questions)} clarifying questions...", "❓")
        answers = await app.question_answer_session_async(questions)

        if answers is None:
            # User cancelled
            app.show_message("Discovery cancelled", "warning")
            return False

        # Store round
        qa_rounds.append({"questions": questions, "answers": answers})
        state.qa_rounds = qa_rounds
        save_state(state)

        # Update discovery log
        _write_discovery_log(state.task_name, qa_rounds)

        app.show_message(f"Round {len(qa_rounds)} complete - {len(questions)} Q&As recorded", "success")

        # Ask if user wants more questions
        more_questions = await app.ask_yes_no_async("Got more questions?")
        if not more_questions:
            break

    # Mark discovery complete
    state.qa_complete = True
    state.pm_subphase = "specifying"
    save_state(state)

    if qa_rounds:
        app.show_message(f"Discovery complete - {len(qa_rounds)} rounds of Q&A", "success")
    else:
        app.show_message("Discovery complete - no questions needed", "info")

    return True


async def _generate_discovery_questions(
    app: WorkflowTUIApp,
    state: WorkflowState,
    builder: PromptBuilder,
    qa_history: list[dict],
) -> list[str] | None:
    """
    Generate discovery questions by invoking the AI.

    Returns:
        List of questions, empty list if AI found no gaps, or None if failed.
    """
    from galangal.ai.claude import ClaudeBackend
    from galangal.ui.tui import TUIAdapter

    prompt = builder.build_discovery_prompt(state, qa_history)

    # Log the prompt
    logs_dir = get_task_dir(state.task_name) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    round_num = len(qa_history) + 1
    log_file = logs_dir / f"discovery_{round_num}.log"
    with open(log_file, "w") as f:
        f.write(f"=== Discovery Prompt (Round {round_num}) ===\n{prompt}\n\n")

    # Run AI
    backend = ClaudeBackend()
    ui = TUIAdapter(app)
    result = await asyncio.to_thread(
        backend.invoke,
        prompt=prompt,
        timeout=300,  # 5 minutes for question generation
        max_turns=10,
        ui=ui,
        pause_check=lambda: app._paused,
    )

    # Log output
    with open(log_file, "a") as f:
        f.write(f"=== Output ===\n{result.output or result.message}\n")

    if not result.success:
        return None

    # Parse questions from output
    return _parse_discovery_questions(result.output or "")


def _parse_discovery_questions(output: str) -> list[str]:
    """Parse questions from AI output."""
    # Check for NO_QUESTIONS marker
    if "# NO_QUESTIONS" in output or "#NO_QUESTIONS" in output:
        return []

    questions = []
    lines = output.split("\n")
    in_questions = False

    for line in lines:
        line = line.strip()

        # Start capturing after DISCOVERY_QUESTIONS header
        if "DISCOVERY_QUESTIONS" in line:
            in_questions = True
            continue

        if in_questions and line:
            # Match numbered questions (1. Question text)
            import re
            match = re.match(r"^\d+[\.\)]\s*(.+)$", line)
            if match:
                questions.append(match.group(1))
            elif line.startswith("-"):
                # Also accept bullet points
                questions.append(line[1:].strip())

    return questions


def _write_discovery_log(task_name: str, qa_rounds: list[dict]) -> None:
    """Write or update DISCOVERY_LOG.md artifact."""
    content_parts = ["# Discovery Log\n"]
    content_parts.append("This log captures the Q&A from brief refinement.\n")

    for i, round_data in enumerate(qa_rounds, 1):
        content_parts.append(f"\n## Round {i}\n")
        content_parts.append("\n### Questions\n")
        for j, q in enumerate(round_data.get("questions", []), 1):
            content_parts.append(f"{j}. {q}\n")
        content_parts.append("\n### Answers\n")
        for j, a in enumerate(round_data.get("answers", []), 1):
            content_parts.append(f"{j}. {a}\n")

    write_artifact("DISCOVERY_LOG.md", "".join(content_parts), task_name)


# -----------------------------------------------------------------------------
# Helper functions for workflow logic
# -----------------------------------------------------------------------------


def _build_preflight_error_message(result) -> str:
    """Build error message for preflight failure modal."""
    detailed_error = result.output or result.message

    failed_lines = []
    for line in detailed_error.split("\n"):
        if (
            line.strip().startswith("✗")
            or "Failed" in line
            or "Missing" in line
            or "Error" in line
        ):
            failed_lines.append(line.strip())

    modal_message = "Preflight checks failed:\n\n"
    if failed_lines:
        modal_message += "\n".join(failed_lines[:10])
    else:
        modal_message += detailed_error[:500]
    modal_message += "\n\nFix issues and retry?"

    return modal_message


async def _handle_max_retries_exceeded(
    app: WorkflowTUIApp,
    state: WorkflowState,
    error_message: str,
    max_retries: int,
) -> str:
    """Handle stage failure after max retries exceeded."""
    error_preview = error_message[:800].strip()
    if len(error_message) > 800:
        error_preview += "..."

    # Show error prominently in error panel
    app.show_error(
        f"Stage {state.stage.value} failed after {max_retries} attempts",
        error_preview,
    )

    modal_message = (
        f"Stage {state.stage.value} failed after {max_retries} attempts.\n\n"
        f"Error:\n{error_preview}\n\n"
        "What would you like to do?"
    )

    choice = await app.prompt_async(PromptType.STAGE_FAILURE, modal_message)

    # Clear error panel when user makes a choice
    app.clear_error()

    if choice == "fix_in_dev":
        feedback = await app.multiline_input_async(
            "Describe what needs to be fixed (Ctrl+S to submit):", ""
        )
        feedback = feedback or "Fix the failing stage"

        failing_stage = state.stage.value
        state.stage = Stage.DEV
        state.last_failure = (
            f"Feedback from {failing_stage} failure: {feedback}\n\n"
            f"Original error:\n{error_message[:1500]}"
        )
        state.reset_attempts(clear_failure=False)
        app.show_message("Rolling back to DEV with feedback", "warning")
        save_state(state)

    return choice


async def _handle_plan_approval(
    app: WorkflowTUIApp, state: WorkflowState, config
) -> bool:
    """
    Handle plan approval gate after PM stage.

    Returns True if workflow should continue, False if rejected/quit.
    """
    default_approver = config.project.approver_name or ""

    choice = await app.prompt_async(
        PromptType.PLAN_APPROVAL, "Approve plan to continue?"
    )

    if choice == "yes":
        name = await app.text_input_async("Enter approver name:", default_approver)
        if name:
            from datetime import datetime, timezone

            approval_content = f"""# Plan Approval

- **Status:** Approved
- **Approved By:** {name}
- **Date:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
"""
            write_artifact("APPROVAL.md", approval_content, state.task_name)
            app.show_message(f"Plan approved by {name}", "success")
            return True
        else:
            # Cancelled - ask again
            return await _handle_plan_approval(app, state, config)

    elif choice == "no":
        reason = await app.multiline_input_async(
            "Enter rejection reason (Ctrl+S to submit):", "Needs revision"
        )
        if reason:
            state.stage = Stage.PM
            state.last_failure = f"Plan rejected: {reason}"
            state.reset_attempts(clear_failure=False)
            save_state(state)
            app.show_message(f"Plan rejected: {reason}", "warning")
            app.show_message("Restarting PM stage with feedback...", "info")
            return False
        else:
            # Cancelled - ask again
            return await _handle_plan_approval(app, state, config)

    else:  # quit
        app._workflow_result = "paused"
        return False


def _show_skipped_stages(
    app: WorkflowTUIApp, current_stage: Stage, next_stage: Stage
) -> None:
    """Show messages for any stages that were skipped."""
    expected_next_idx = STAGE_ORDER.index(current_stage) + 1
    actual_next_idx = STAGE_ORDER.index(next_stage)
    if actual_next_idx > expected_next_idx:
        skipped = STAGE_ORDER[expected_next_idx:actual_next_idx]
        for s in skipped:
            app.show_message(f"Skipped {s.value} (condition not met)", "info")


async def _handle_workflow_complete(app: WorkflowTUIApp, state: WorkflowState) -> None:
    """Handle workflow completion - finalization and post-completion options."""
    app.show_workflow_complete()
    app.update_stage("COMPLETE")
    app.set_status("complete", "workflow finished")

    choice = await app.prompt_async(PromptType.COMPLETION, "Workflow complete!")

    if choice == "yes":
        # Run finalization
        app.set_status("finalizing", "creating PR...")

        def progress_callback(message, status):
            app.show_message(message, status)

        from galangal.commands.complete import finalize_task

        success, pr_url = await asyncio.to_thread(
            finalize_task,
            state.task_name,
            state,
            force=True,
            progress_callback=progress_callback,
        )

        if success:
            app.add_activity("")
            app.add_activity("[bold #b8bb26]Task completed successfully![/]", "✓")
            if pr_url and pr_url != "PR already exists":
                app.add_activity(f"[#83a598]PR: {pr_url}[/]", "")
            app.add_activity("")

        # Show post-completion options
        completion_msg = "Task completed successfully!"
        if pr_url and pr_url.startswith("http"):
            completion_msg += f"\n\nPull Request:\n{pr_url}"
        completion_msg += "\n\nWhat would you like to do next?"

        post_choice = await app.prompt_async(PromptType.POST_COMPLETION, completion_msg)

        if post_choice == "new_task":
            app._workflow_result = "new_task"
        else:
            app._workflow_result = "done"

    elif choice == "no":
        # Ask for feedback
        app.set_status("feedback", "waiting for input")
        feedback = await app.multiline_input_async(
            "What needs to be fixed? (Ctrl+S to submit):", ""
        )

        if feedback:
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
        state.reset_attempts(clear_failure=False)
        save_state(state)
        app._workflow_result = "back_to_dev"

    else:
        app._workflow_result = "paused"


def _start_new_task_tui() -> str:
    """
    Create a new task using TUI prompts for task type and description.

    Returns:
        Result string indicating outcome.
    """
    app = WorkflowTUIApp("New Task", "SETUP", hidden_stages=frozenset())

    task_info = {"type": None, "description": None, "name": None}

    async def task_creation_loop():
        """Async task creation flow."""
        try:
            app.add_activity("[bold]Starting new task...[/bold]", "🆕")
            app.set_status("setup", "select task type")

            # Step 1: Get task type
            type_choice = await app.prompt_async(
                PromptType.TASK_TYPE, "Select task type:"
            )

            if type_choice == "quit":
                app._workflow_result = "cancelled"
                app.set_timer(0.5, app.exit)
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
            task_info["type"] = type_map.get(type_choice, TaskType.FEATURE)
            app.show_message(f"Task type: {task_info['type'].display_name()}", "success")

            # Step 2: Get task description
            app.set_status("setup", "enter description")
            description = await app.multiline_input_async(
                "Enter task description (Ctrl+S to submit):", ""
            )

            if not description:
                app.show_message("Task creation cancelled", "warning")
                app._workflow_result = "cancelled"
                app.set_timer(0.5, app.exit)
                return

            task_info["description"] = description

            # Step 3: Generate and create task
            app.set_status("setup", "generating task name")
            from galangal.commands.start import create_task, generate_task_name

            task_name = await asyncio.to_thread(
                generate_task_name, task_info["description"]
            )
            task_info["name"] = task_name
            app.show_message(f"Task name: {task_name}", "info")

            # Create the task
            app.set_status("setup", "creating task")
            success, message = await asyncio.to_thread(
                create_task,
                task_name,
                task_info["description"],
                task_info["type"],
            )

            if success:
                app.show_message(message, "success")
                app._workflow_result = "task_created"
            else:
                app.show_error("Task creation failed", message)
                app._workflow_result = "error"

        except Exception as e:
            app.show_error("Task creation error", str(e))
            app._workflow_result = "error"
        finally:
            app.set_timer(0.5, app.exit)

    # Start creation as async worker
    app.call_later(lambda: app.run_worker(task_creation_loop(), exclusive=True))
    app.run()

    result = app._workflow_result or "cancelled"

    if result == "task_created" and task_info["name"]:
        from galangal.core.state import load_state

        new_state = load_state(task_info["name"])
        if new_state:
            return _run_workflow_with_tui(new_state)

    return result
