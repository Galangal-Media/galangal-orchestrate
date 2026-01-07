"""
Workflow execution - stage execution, rollback, loop handling.
"""

import signal
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console

from galangal.config.loader import get_config, get_tasks_dir
from galangal.core.artifacts import artifact_exists, read_artifact, write_artifact, artifact_path
from galangal.core.state import (
    Stage,
    WorkflowState,
    STAGE_ORDER,
    save_state,
    get_task_dir,
    should_skip_for_task_type,
    get_hidden_stages_for_task_type,
)
from galangal.core.tasks import get_current_branch
from galangal.ai.claude import set_pause_requested, get_pause_requested
from galangal.prompts.builder import PromptBuilder
from galangal.validation.runner import ValidationRunner
from galangal.ui.tui import run_stage_with_tui, TUIAdapter, WorkflowTUIApp, PromptType
from galangal.ai.claude import ClaudeBackend

console = Console()

# Global state for pause handling
_current_state: Optional[WorkflowState] = None


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGINT (Ctrl+C) gracefully."""
    set_pause_requested(True)
    console.print(
        "\n\n[yellow]⏸️  Pause requested - finishing current operation...[/yellow]"
    )
    console.print("[dim]   (Press Ctrl+C again to force quit)[/dim]\n")


def get_next_stage(
    current: Stage, state: WorkflowState
) -> Optional[Stage]:
    """Get the next stage, handling conditional stages and task type skipping."""
    config = get_config()
    task_name = state.task_name
    task_type = state.task_type
    idx = STAGE_ORDER.index(current)

    if idx >= len(STAGE_ORDER) - 1:
        return None

    next_stage = STAGE_ORDER[idx + 1]

    # Check config-level skipping
    if next_stage.value in [s.upper() for s in config.stages.skip]:
        return get_next_stage(next_stage, state)

    # Check task type skipping
    if should_skip_for_task_type(next_stage, task_type):
        return get_next_stage(next_stage, state)

    # Check conditional stages via validation runner
    runner = ValidationRunner()
    if next_stage == Stage.MIGRATION:
        if artifact_exists("MIGRATION_SKIP.md", task_name):
            return get_next_stage(next_stage, state)
        # Check skip condition
        result = runner.validate_stage("MIGRATION", task_name)
        if result.message.endswith("(condition met)"):
            return get_next_stage(next_stage, state)

    elif next_stage == Stage.CONTRACT:
        if artifact_exists("CONTRACT_SKIP.md", task_name):
            return get_next_stage(next_stage, state)
        result = runner.validate_stage("CONTRACT", task_name)
        if result.message.endswith("(condition met)"):
            return get_next_stage(next_stage, state)

    elif next_stage == Stage.BENCHMARK:
        if artifact_exists("BENCHMARK_SKIP.md", task_name):
            return get_next_stage(next_stage, state)
        result = runner.validate_stage("BENCHMARK", task_name)
        if result.message.endswith("(condition met)"):
            return get_next_stage(next_stage, state)

    return next_stage


def execute_stage(state: WorkflowState, tui_app: WorkflowTUIApp = None) -> tuple[bool, str]:
    """Execute the current stage. Returns (success, message).

    If tui_app is provided, uses the persistent TUI instead of creating a new one.
    """
    stage = state.stage
    task_name = state.task_name
    config = get_config()

    if stage == Stage.COMPLETE:
        return True, "Workflow complete"

    # Design approval gate (only in legacy mode without TUI)
    if stage == Stage.DEV and tui_app is None:
        from galangal.commands.approve import prompt_design_approval
        design_skipped = artifact_exists(
            "DESIGN_SKIP.md", task_name
        ) or should_skip_for_task_type(Stage.DESIGN, state.task_type)

        if design_skipped:
            pass
        elif not artifact_exists("DESIGN_REVIEW.md", task_name):
            result = prompt_design_approval(task_name, state)
            if result == "quit":
                return False, "PAUSED: User requested pause"
            elif result == "rejected":
                return True, "Design rejected - restarting from DESIGN"

    # Check for clarification
    if artifact_exists("QUESTIONS.md", task_name) and not artifact_exists(
        "ANSWERS.md", task_name
    ):
        state.clarification_required = True
        save_state(state)
        return False, "Clarification required. Please provide ANSWERS.md."

    # PREFLIGHT runs validation directly
    if stage == Stage.PREFLIGHT:
        if tui_app:
            tui_app.add_activity("Running preflight checks...", "⚙")
        else:
            console.print("[dim]Running preflight checks...[/dim]")

        runner = ValidationRunner()
        result = runner.validate_stage("PREFLIGHT", task_name)

        if result.success:
            if tui_app:
                tui_app.show_message(f"Preflight: {result.message}", "success")
            else:
                console.print(f"[green]✓ Preflight: {result.message}[/green]")
            return True, result.message
        else:
            # Include detailed output in the failure message for display
            detailed_message = result.message
            if result.output:
                detailed_message = f"{result.message}\n\n{result.output}"
            # Return special marker so workflow knows this is preflight failure
            return False, f"PREFLIGHT_FAILED:{detailed_message}"

    # Get current branch for UI
    branch = get_current_branch()

    # Build prompt
    builder = PromptBuilder()
    prompt = builder.build_full_prompt(stage, state)

    # Add retry context
    if state.attempt > 1 and state.last_failure:
        retry_context = f"""
## ⚠️ RETRY ATTEMPT {state.attempt}

The previous attempt failed with the following error:

```
{state.last_failure[:1000]}
```

Please fix the issue above before proceeding. Do not repeat the same mistake.
"""
        prompt = f"{prompt}\n\n{retry_context}"

    # Log the prompt
    logs_dir = get_task_dir(task_name) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{stage.value.lower()}_{state.attempt}.log"
    with open(log_file, "w") as f:
        f.write(f"=== Prompt ===\n{prompt}\n\n")

    # Run stage - either with persistent TUI or standalone
    if tui_app:
        # Use the persistent TUI
        backend = ClaudeBackend()
        ui = TUIAdapter(tui_app)
        success, output = backend.invoke(
            prompt=prompt,
            timeout=14400,
            max_turns=200,
            ui=ui,
        )
    else:
        # Create new TUI for this stage
        success, output = run_stage_with_tui(
            task_name=task_name,
            stage=stage.value,
            branch=branch,
            attempt=state.attempt,
            prompt=prompt,
        )

    # Log the output
    with open(log_file, "a") as f:
        f.write(f"=== Output ===\n{output}\n")

    if not success:
        return False, output

    # Validate stage
    if tui_app:
        tui_app.add_activity("Validating stage outputs...", "⚙")
    else:
        console.print("[dim]Validating stage outputs...[/dim]")

    runner = ValidationRunner()
    result = runner.validate_stage(stage.value, task_name)

    with open(log_file, "a") as f:
        f.write(f"\n=== Validation ===\n{result.message}\n")

    if result.success:
        if tui_app:
            tui_app.show_message(result.message, "success")
        else:
            console.print(f"[green]✓ {result.message}[/green]")
    else:
        if tui_app:
            tui_app.show_message(result.message, "error")
        else:
            console.print(f"[red]✗ {result.message}[/red]")

    # Include rollback target in message if validation failed
    if not result.success and result.rollback_to:
        return False, f"ROLLBACK:{result.rollback_to}:{result.message}"

    return result.success, result.message


def archive_rollback_if_exists(task_name: str) -> None:
    """Archive ROLLBACK.md after DEV stage succeeds."""
    if not artifact_exists("ROLLBACK.md", task_name):
        return

    rollback_content = read_artifact("ROLLBACK.md", task_name)
    resolved_path = artifact_path("ROLLBACK_RESOLVED.md", task_name)

    resolution_note = f"\n\n## Resolved: {datetime.now(timezone.utc).isoformat()}\n\nIssues fixed by DEV stage.\n"

    if resolved_path.exists():
        existing = resolved_path.read_text()
        resolved_path.write_text(
            existing + "\n---\n" + rollback_content + resolution_note
        )
    else:
        resolved_path.write_text(rollback_content + resolution_note)

    rollback_path = artifact_path("ROLLBACK.md", task_name)
    rollback_path.unlink()

    console.print("   [dim]📋 Archived ROLLBACK.md → ROLLBACK_RESOLVED.md[/dim]")


def handle_rollback(state: WorkflowState, message: str) -> bool:
    """Handle a rollback signal from a stage validator."""
    runner = ValidationRunner()

    # Check for rollback_to in validation result
    if not message.startswith("ROLLBACK:") and "rollback" not in message.lower():
        return False

    # Parse rollback target
    target_stage = Stage.DEV  # Default rollback target

    if message.startswith("ROLLBACK:"):
        parts = message.split(":", 2)
        if len(parts) >= 2:
            try:
                target_stage = Stage.from_str(parts[1])
            except ValueError:
                pass

    task_name = state.task_name
    from_stage = state.stage

    reason = message.split(":", 2)[-1] if ":" in message else message

    rollback_entry = f"""
## Rollback from {from_stage.value}

**Date:** {datetime.now(timezone.utc).isoformat()}
**From Stage:** {from_stage.value}
**Target Stage:** {target_stage.value}
**Reason:** {reason}

### Required Actions
{reason}

---
"""

    existing = read_artifact("ROLLBACK.md", task_name)
    if existing:
        new_content = existing + rollback_entry
    else:
        new_content = f"# Rollback Log\n\nThis file tracks issues that required rolling back to earlier stages.\n{rollback_entry}"

    write_artifact("ROLLBACK.md", new_content, task_name)

    state.stage = target_stage
    state.attempt = 1
    state.last_failure = f"Rollback from {from_stage.value}: {reason}"
    save_state(state)

    console.print(
        f"\n[yellow]⚠️  ROLLBACK: {from_stage.value} → {target_stage.value}[/yellow]"
    )
    console.print(f"   Reason: {reason}")
    console.print("   See ROLLBACK.md for details\n")

    return True


def run_workflow(state: WorkflowState) -> None:
    """Run the workflow from current state to completion or failure."""
    import os
    import threading

    # Try persistent TUI first (unless disabled)
    if not os.environ.get("GALANGAL_NO_TUI"):
        try:
            result = _run_workflow_with_tui(state)
            if result != "use_legacy":
                # TUI handled the workflow
                return
        except Exception as e:
            console.print(f"[yellow]TUI error: {e}. Using legacy mode.[/yellow]")

    # Legacy mode (no persistent TUI)
    _run_workflow_legacy(state)


def _run_workflow_with_tui(state: WorkflowState) -> str:
    """Run workflow with persistent TUI. Returns result or 'use_legacy' to fall back."""
    import threading

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
                success, message = execute_stage(state, tui_app=app)

                if app._paused:
                    app._workflow_result = "paused"
                    break

                if not success:
                    app.show_stage_complete(state.stage.value, False)

                    # Handle preflight failures specially - don't auto-retry
                    if message.startswith("PREFLIGHT_FAILED:"):
                        detailed_error = message[len("PREFLIGHT_FAILED:") :]
                        app.show_message("Preflight checks failed", "error")
                        # Show the detailed report in the activity log
                        for line in detailed_error.strip().split("\n"):
                            if line.strip():
                                app.add_activity(line)

                        # Prompt user to retry after fixing
                        retry_event = threading.Event()
                        retry_result = {"value": None}

                        def handle_preflight_retry(choice):
                            retry_result["value"] = choice
                            retry_event.set()

                        app.show_prompt(
                            PromptType.PREFLIGHT_RETRY,
                            "Fix environment issues and retry?",
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

                    if state.awaiting_approval or state.clarification_required:
                        app.show_message(message, "warning")
                        save_state(state)
                        app._workflow_result = "paused"
                        break

                    if handle_rollback(state, message):
                        app.show_message(f"Rolling back: {message[:80]}", "warning")
                        continue

                    state.attempt += 1
                    state.last_failure = message

                    if state.attempt > max_retries:
                        app.show_message(f"Max retries ({max_retries}) exceeded for {state.stage.value}", "error")
                        # Show the failure details in the activity log
                        app.add_activity("")
                        app.add_activity("[bold red]Last failure:[/bold red]")
                        for line in message[:2000].split("\n"):
                            if line.strip():
                                app.add_activity(f"  {line}")

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

                                app.show_text_input(
                                    "Describe what needs to be fixed:",
                                    handle_feedback,
                                )
                            else:
                                failure_event.set()

                        app.show_prompt(
                            PromptType.STAGE_FAILURE,
                            f"Stage {state.stage.value} failed after {max_retries} attempts. What would you like to do?",
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
                            state.last_failure = f"Feedback from {failing_stage} failure: {feedback}\n\nOriginal error:\n{message[:1500]}"
                            app.show_message(f"Rolling back to DEV with feedback", "warning")
                            save_state(state)
                            continue
                        else:
                            save_state(state)
                            app._workflow_result = "paused"
                            break

                    app.show_message(f"Retrying (attempt {state.attempt}/{max_retries})...", "warning")
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
                            app.show_prompt(PromptType.PLAN_APPROVAL, "Approve plan to continue?", handle_approval)
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
                            app.show_prompt(PromptType.PLAN_APPROVAL, "Approve plan to continue?", handle_approval)
                            return  # Don't set event - wait for new choice
                        approval_event.set()

                    app.show_prompt(PromptType.PLAN_APPROVAL, "Approve plan to continue?", handle_approval)

                    # Wait for choice, then potentially for name or reason
                    while not approval_event.is_set():
                        approval_event.wait(timeout=0.1)
                        if approval_result["value"] == "pending_name":
                            approval_result["value"] = None  # Reset
                            app.show_text_input("Enter approver name:", default_approver, handle_approver_name)
                        elif approval_result["value"] == "pending_reason":
                            approval_result["value"] = None  # Reset
                            app.show_text_input("Enter rejection reason:", "Needs revision", handle_rejection_reason)

                    if approval_result["value"] == "quit":
                        app._workflow_result = "paused"
                        break
                    elif approval_result["value"] == "rejected":
                        app.show_message("Restarting PM stage with feedback...", "info")
                        continue

                if state.stage == Stage.DEV:
                    archive_rollback_if_exists(state.task_name)

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
                    app._workflow_result = "create_pr"
                elif completion_result["value"] == "no":
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

    if result == "create_pr":
        from galangal.commands.complete import finalize_task
        finalize_task(state.task_name, state, force=False)
    elif result == "back_to_dev":
        # Restart workflow from DEV
        return _run_workflow_with_tui(state)
    elif result == "paused":
        _handle_pause(state)

    return result


def _run_workflow_legacy(state: WorkflowState) -> None:
    """Run workflow without persistent TUI (legacy mode)."""
    from galangal.commands.approve import prompt_plan_approval
    from galangal.commands.complete import finalize_task

    global _current_state
    config = get_config()
    max_retries = config.stages.max_retries

    _current_state = state
    original_handler = signal.signal(signal.SIGINT, _signal_handler)

    try:
        while True:
            # Run stages until COMPLETE
            while state.stage != Stage.COMPLETE:
                if get_pause_requested():
                    _handle_pause(state)
                    return

                success, message = execute_stage(state)

                if get_pause_requested() or message == "PAUSED: User requested pause":
                    _handle_pause(state)
                    return

                if not success:
                    # Handle preflight failures specially - don't auto-retry
                    if message.startswith("PREFLIGHT_FAILED:"):
                        detailed_error = message[len("PREFLIGHT_FAILED:") :]
                        console.print("\n[red]✗ Preflight checks failed[/red]\n")
                        console.print(detailed_error)
                        console.print()

                        # Prompt user to retry after fixing
                        while True:
                            console.print("[yellow]Fix environment issues and retry?[/yellow]")
                            console.print("  [bold]1[/bold] Retry")
                            console.print("  [bold]2[/bold] Quit")
                            choice = console.input("\n[bold]Choice:[/bold] ").strip()
                            if choice == "1":
                                console.print("\n[dim]Retrying preflight checks...[/dim]")
                                break  # Break out of while loop, continue outer loop
                            elif choice == "2":
                                save_state(state)
                                return
                            else:
                                console.print("[red]Invalid choice. Please enter 1 or 2.[/red]\n")
                        continue  # Retry without incrementing attempt

                    if state.awaiting_approval or state.clarification_required:
                        console.print(f"\n{message}")
                        save_state(state)
                        return

                    if handle_rollback(state, message):
                        continue

                    state.attempt += 1
                    state.last_failure = message

                    if state.attempt > max_retries:
                        console.print(
                            f"\n[red]Max retries ({max_retries}) exceeded for stage {state.stage.value}[/red]"
                        )
                        console.print("\n[bold]Last failure:[/bold]")
                        console.print(message[:2000])
                        console.print()

                        # Prompt user for what to do
                        while True:
                            console.print(f"[yellow]Stage {state.stage.value} failed after {max_retries} attempts. What would you like to do?[/yellow]")
                            console.print("  [bold]1[/bold] Retry (reset attempts)")
                            console.print("  [bold]2[/bold] Fix in DEV (add feedback and roll back)")
                            console.print("  [bold]3[/bold] Quit")
                            choice = console.input("\n[bold]Choice:[/bold] ").strip()

                            if choice == "1":
                                state.attempt = 1  # Reset attempts
                                console.print("\n[dim]Retrying stage...[/dim]")
                                save_state(state)
                                break
                            elif choice == "2":
                                feedback = console.input("\n[bold]Describe what needs to be fixed:[/bold] ").strip()
                                if not feedback:
                                    feedback = "Fix the failing stage"
                                failing_stage = state.stage.value
                                state.stage = Stage.DEV
                                state.attempt = 1
                                state.last_failure = f"Feedback from {failing_stage} failure: {feedback}\n\nOriginal error:\n{message[:1500]}"
                                console.print("\n[yellow]Rolling back to DEV with feedback[/yellow]")
                                save_state(state)
                                break
                            elif choice == "3":
                                save_state(state)
                                return
                            else:
                                console.print("[red]Invalid choice. Please enter 1, 2, or 3.[/red]\n")
                        continue

                    console.print(
                        f"\n[yellow]Stage failed, retrying (attempt {state.attempt}/{max_retries})...[/yellow]"
                    )
                    console.print(f"Failure: {message[:500]}...")
                    save_state(state)
                    continue

                console.print(
                    f"\n[green]Stage {state.stage.value} completed successfully[/green]"
                )

                # Plan approval gate
                if state.stage == Stage.PM and not artifact_exists("APPROVAL.md", state.task_name):
                    result = prompt_plan_approval(state.task_name, state)
                    if result == "quit":
                        _handle_pause(state)
                        return
                    elif result == "rejected":
                        continue

                if state.stage == Stage.DEV:
                    archive_rollback_if_exists(state.task_name)

                next_stage = get_next_stage(state.stage, state)
                if next_stage:
                    expected_next_idx = STAGE_ORDER.index(state.stage) + 1
                    actual_next_idx = STAGE_ORDER.index(next_stage)
                    if actual_next_idx > expected_next_idx:
                        skipped = STAGE_ORDER[expected_next_idx:actual_next_idx]
                        for s in skipped:
                            console.print(
                                f"   [dim]⏭️  Skipped {s.value} (condition not met)[/dim]"
                            )

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
            console.print("\n" + "=" * 60)
            console.print("[bold green]WORKFLOW COMPLETE[/bold green]")
            console.print("=" * 60)

            from rich.prompt import Prompt

            console.print("\n[bold]Options:[/bold]")
            console.print("  [green]y[/green] - Create PR and finalize")
            console.print("  [yellow]n[/yellow] - Review and make changes (go back to DEV)")
            console.print("  [yellow]q[/yellow] - Quit (finalize later with 'galangal complete')")

            while True:
                choice = Prompt.ask("Your choice", default="y").strip().lower()

                if choice in ["y", "yes"]:
                    finalize_task(state.task_name, state, force=False)
                    return
                elif choice in ["n", "no"]:
                    state.stage = Stage.DEV
                    state.attempt = 1
                    save_state(state)
                    console.print("\n[dim]Going back to DEV stage...[/dim]")
                    break
                elif choice in ["q", "quit"]:
                    _handle_pause(state)
                    return
                else:
                    console.print("[red]Invalid choice. Enter y/n/q[/red]")

    finally:
        signal.signal(signal.SIGINT, original_handler)
        _current_state = None


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
