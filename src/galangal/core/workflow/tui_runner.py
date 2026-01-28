"""
TUI-based workflow runner using persistent Textual app with async/await.

This module uses Textual's async capabilities for cleaner coordination
between UI events and workflow logic, eliminating manual threading.Event
coordination in favor of asyncio.Future-based prompts.

The workflow logic is delegated to WorkflowEngine, which handles all state
transitions. This module is responsible for:
- UI orchestration (displaying events, collecting input)
- Translating engine events to visual updates
- Collecting user input and passing actions to the engine
"""

import asyncio
from typing import Any

from rich.console import Console

from galangal.config.loader import get_config
from galangal.config.schema import GalangalConfig
from galangal.core.artifacts import parse_stage_plan, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    TASK_TYPE_SKIP_STAGES,
    Stage,
    TaskType,
    WorkflowState,
    get_conditional_stages,
    get_hidden_stages_for_task_type,
    get_task_dir,
    save_state,
)
from galangal.core.workflow.engine import (
    ActionType,
    EventType,
    WorkflowEngine,
    WorkflowEvent,
    action,
)
from galangal.core.workflow.pause import _handle_pause
from galangal.prompts.builder import PromptBuilder
from galangal.ui.tui import PromptType, WorkflowTUIApp
from galangal.validation.runner import ValidationRunner

console = Console()


async def _init_hub_client(config: GalangalConfig, state: WorkflowState) -> None:
    """Initialize hub client if configured."""
    if not config.hub.enabled:
        return

    try:
        from pathlib import Path

        from galangal.hub.action_handler import get_action_handler
        from galangal.hub.client import HubClient, set_hub_client
        from galangal.hub.hooks import set_main_loop

        # Store main loop for thread-safe async scheduling
        set_main_loop(asyncio.get_running_loop())

        project_path = Path.cwd()
        client = HubClient(
            config=config.hub,
            project_name=config.project.name,
            project_path=project_path,
        )

        # Register action handler
        handler = get_action_handler()
        client.on_action(handler.handle_hub_action)

        # Connect to hub
        connected = await client.connect()
        if connected:
            set_hub_client(client)
            # Send initial state
            await client.send_state(state)
    except Exception:
        # Hub connection failure is non-fatal
        pass


async def _cleanup_hub_client() -> None:
    """Cleanup hub client on workflow exit."""
    from galangal.hub.client import get_hub_client, set_hub_client

    client = get_hub_client()
    if client:
        await client.disconnect()
        set_hub_client(None)


def _run_workflow_with_tui(
    state: WorkflowState,
    ignore_staleness: bool = False,
) -> str:
    """
    Execute the workflow loop with a persistent Textual TUI.

    This is the main entry point for running workflows interactively. It creates
    a WorkflowTUIApp and runs the stage pipeline using async/await for clean
    coordination between UI and workflow logic.

    The workflow logic is delegated to WorkflowEngine. This function handles:
    - UI orchestration
    - Translating engine events to visual updates
    - Collecting user input for interactive prompts

    Threading Model (Async):
        - Main thread: Runs the Textual TUI event loop
        - Async worker: Executes workflow logic using Textual's run_worker()
        - Blocking operations (execute_stage) run in thread executor

    Args:
        state: Current workflow state containing task info, current stage,
            attempt count, and failure information.
        ignore_staleness: If True, skip lineage staleness checks on resume.

    Returns:
        Result string indicating outcome:
        - "done": Workflow completed successfully and user chose to exit
        - "new_task": User chose to create a new task after completion
        - "paused": Workflow was paused (Ctrl+C or user quit)
        - "back_to_dev": User requested changes at completion, rolling back
        - "error": An exception occurred during execution
    """
    config = get_config()

    # Store ignore_staleness flag for use in workflow loop
    state._ignore_staleness = ignore_staleness

    # Compute hidden stages based on task type and config
    hidden_stages = frozenset(get_hidden_stages_for_task_type(state.task_type, config.stages.skip))
    activity_log_path = None
    if config.logging.activity_file:
        activity_log_path = config.logging.activity_file.format(task_name=state.task_name)

    app = WorkflowTUIApp(
        state.task_name,
        state.stage.value,
        hidden_stages=hidden_stages,
        stage_durations=state.stage_durations,
        activity_log_path=activity_log_path,
    )

    # Create workflow engine
    engine = WorkflowEngine(state, config)

    # Track if we've already checked staleness on this resume
    staleness_checked = False

    async def workflow_loop() -> None:
        """Async workflow loop running within Textual's event loop."""
        nonlocal staleness_checked

        # Initialize hub client if configured
        await _init_hub_client(config, state)

        try:
            while not engine.is_complete and not app._paused:
                # Check GitHub issue status
                github_event = await asyncio.to_thread(engine.check_github_issue)
                if github_event:
                    app.show_message(github_event.message, "warning")
                    app.add_activity(
                        f"Issue #{state.github_issue} closed externally - pausing", "⚠"
                    )
                    app._workflow_result = "paused"
                    break

                # Check for stale stages on resume (once per resume)
                if not staleness_checked and config.lineage.enabled:
                    staleness_checked = True
                    ignore = getattr(state, "_ignore_staleness", False)
                    if not ignore:
                        should_continue = await _check_staleness_on_resume(
                            app, state, config
                        )
                        if not should_continue:
                            app._workflow_result = "paused"
                            break

                app.update_stage(engine.current_stage.value, state.attempt)
                app.set_status("running", f"executing {engine.current_stage.value}")

                # Start stage timer
                engine.start_stage_timer()

                # Run PM discovery Q&A before PM stage execution
                if engine.current_stage == Stage.PM and not state.qa_complete:
                    skip_discovery = getattr(state, "_skip_discovery", False)
                    discovery_ok = await _run_pm_discovery(app, state, skip_discovery)
                    if not discovery_ok:
                        app._workflow_result = "paused"
                        break
                    app.set_status("running", f"executing {engine.current_stage.value}")

                # Execute stage in thread executor
                workflow_event = await asyncio.to_thread(
                    engine.execute_current_stage,
                    app,
                    lambda: app._paused,
                )

                # Handle user interrupt requests (Ctrl+I, Ctrl+N, Ctrl+B, Ctrl+E)
                interrupt_result = await _handle_user_interrupts(app, engine)
                if interrupt_result == "continue":
                    continue
                elif interrupt_result == "paused":
                    app._workflow_result = "paused"
                    break

                if app._paused:
                    app._workflow_result = "paused"
                    break

                # Handle the workflow event
                result = await _handle_workflow_event(app, engine, workflow_event, config)
                if result == "break":
                    break
                elif result == "continue":
                    continue

            # Workflow complete
            if engine.is_complete:
                await _handle_workflow_complete(app, state)

        except Exception as e:
            from galangal.core.utils import debug_exception

            debug_exception("Workflow execution failed", e)
            app.show_error("Workflow error", str(e))
            app._workflow_result = "error"
            await app.ask_yes_no_async(
                "An error occurred. Press Enter to exit and see details in the debug log."
            )
            app.set_timer(0.5, app.exit)
            return
        finally:
            # Cleanup hub client
            await _cleanup_hub_client()
            if app._workflow_result != "error":
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


# =============================================================================
# Event Handlers - translate engine events to UI updates
# =============================================================================


async def _handle_workflow_event(
    app: WorkflowTUIApp,
    engine: WorkflowEngine,
    event: WorkflowEvent,
    config: GalangalConfig,
) -> str:
    """
    Handle a workflow event from the engine.

    Returns:
        "continue" to continue the loop
        "break" to exit the loop
        "advance" to advance to next stage (handled by caller)
    """
    state = engine.state

    if event.type == EventType.WORKFLOW_PAUSED:
        app._workflow_result = "paused"
        return "break"

    if event.type == EventType.STAGE_COMPLETED:
        app.clear_error()
        duration = state.record_stage_duration()
        app.show_stage_complete(state.stage.value, True, duration)
        if state.stage_durations:
            app.update_stage_durations(state.stage_durations)

        # Advance to next stage via engine
        advance_event = engine.handle_action(action(ActionType.CONTINUE), tui_app=app)
        return await _handle_advance_event(app, engine, advance_event, config)

    if event.type == EventType.APPROVAL_REQUIRED:
        should_continue = await _handle_stage_approval(
            app, state, config, event.data.get("artifact_name", "APPROVAL.md")
        )
        if not should_continue:
            if app._workflow_result == "paused":
                return "break"
            return "continue"  # Rejected - loop back to stage

        # After approval, advance
        advance_event = engine.handle_action(action(ActionType.CONTINUE), tui_app=app)
        return await _handle_advance_event(app, engine, advance_event, config)

    if event.type == EventType.PREFLIGHT_FAILED:
        app.show_stage_complete(state.stage.value, False)
        modal_message = _build_preflight_error_message(event.message, event.data.get("details", ""))
        choice = await app.prompt_async(PromptType.PREFLIGHT_RETRY, modal_message)

        if choice == "retry":
            app.show_message("Retrying preflight checks...", "info")
            return "continue"
        else:
            save_state(state)
            app._workflow_result = "paused"
            return "break"

    if event.type == EventType.CLARIFICATION_REQUIRED:
        app.show_stage_complete(state.stage.value, False)
        questions = event.data.get("questions", [])
        if questions:
            app.show_message(f"Stage has {len(questions)} clarifying question(s)", "warning")
            answers = await app.question_answer_session_async(questions)
            if answers:
                engine.handle_clarification_answers(questions, answers)
                app.show_message("Answers saved - resuming stage", "success")
                return "continue"
            else:
                app.show_message("Answers cancelled - pausing workflow", "warning")
                save_state(state)
                app._workflow_result = "paused"
                return "break"
        else:
            app.show_message("QUESTIONS.md exists but couldn't parse questions", "error")
        save_state(state)
        app._workflow_result = "paused"
        return "break"

    if event.type == EventType.USER_DECISION_REQUIRED:
        app.show_stage_complete(state.stage.value, False)
        artifact_preview = event.data.get("artifact_preview", "")
        full_content = event.data.get("full_content", "")

        while True:
            choice = await app.prompt_async(
                PromptType.USER_DECISION,
                f"Decision file missing for {state.stage.value} stage.\n\n"
                f"Report preview:\n{artifact_preview}\n\n"
                "Please review and decide:",
            )

            if choice == "view":
                app.add_activity("--- Full Report ---", "📄")
                for line in (full_content or "No content").split("\n")[:50]:
                    app.add_activity(line, "")
                app.add_activity("--- End Report ---", "📄")
                continue

            result_event = engine.handle_user_decision(choice, tui_app=app)

            if result_event.type == EventType.WORKFLOW_PAUSED:
                app._workflow_result = "paused"
                return "break"

            if result_event.type == EventType.WORKFLOW_COMPLETE:
                app.show_workflow_complete()
                app._workflow_result = "complete"
                return "break"

            if result_event.type == EventType.ROLLBACK_TRIGGERED:
                app.show_message("Rolling back to DEV per user decision", "warning")
                app.update_stage(state.stage.value, state.attempt)
                return "continue"

            if result_event.type == EventType.STAGE_STARTED:
                # Advanced to next stage
                app.update_stage(state.stage.value, state.attempt)
                return "continue"

            return "continue"

    if event.type == EventType.ROLLBACK_TRIGGERED:
        target = event.data.get("to_stage")
        app.add_activity(f"Rolling back to {target.value if target else 'unknown'}", "⚠")
        app.show_message(f"Rolling back: {event.message[:60]}", "warning")
        app.update_stage(state.stage.value, state.attempt)
        return "continue"

    if event.type == EventType.ROLLBACK_BLOCKED:
        app.show_stage_complete(state.stage.value, False)
        block_reason = event.data.get("block_reason", "")
        target = event.data.get("target_stage", "unknown")

        app.add_activity(f"Rollback blocked: {block_reason}", "⚠")
        app.show_error(f"Rollback blocked: {block_reason}", event.message[:500])

        choice = await app.prompt_async(
            PromptType.STAGE_FAILURE,
            f"Rollback to {target} was blocked.\n\n"
            f"Reason: {block_reason}\n\n"
            f"Error: {event.message[:300]}\n\n"
            "What would you like to do?",
        )
        app.clear_error()

        if choice == "retry":
            state.reset_attempts()
            app.show_message("Retrying stage...", "info")
            save_state(state)
            return "continue"
        elif choice == "fix_in_dev":
            result_event = engine.handle_action(
                action(ActionType.FIX_IN_DEV, error=event.message),
                tui_app=app,
            )
            app.show_message("Rolling back to DEV (manual override)", "warning")
            app.update_stage(state.stage.value, state.attempt)
            return "continue"
        else:
            save_state(state)
            app._workflow_result = "paused"
            return "break"

    if event.type == EventType.MAX_RETRIES_EXCEEDED:
        app.show_stage_complete(state.stage.value, False)
        max_retries = event.data.get("max_retries", config.stages.max_retries)

        # Show error context if available
        error_ctx = event.data.get("error_context")
        if error_ctx:
            # Show last output lines
            for line in error_ctx.last_output_lines[-3:]:
                app.add_activity(f"> {line[:80]}", "📋")
            # Show suggestions
            for suggestion in error_ctx.suggestions:
                app.add_activity(f"Suggestion: {suggestion}", "💡")

        choice = await _handle_max_retries_exceeded(app, state, event.message, max_retries)

        if choice == "retry":
            state.reset_attempts()
            app.show_message("Retrying stage...", "info")
            save_state(state)
            return "continue"
        elif choice == "fix_in_dev":
            # Already handled in _handle_max_retries_exceeded
            return "continue"
        else:
            save_state(state)
            app._workflow_result = "paused"
            return "break"

    if event.type == EventType.STAGE_FAILED:
        app.show_stage_complete(state.stage.value, False)

        # Show error context if available
        error_ctx = event.data.get("error_context")
        if error_ctx:
            # Show suggestions in activity log
            for suggestion in error_ctx.suggestions[:2]:  # First 2 suggestions
                app.add_activity(f"Tip: {suggestion}", "💡")

        app.show_message(
            f"Retrying (attempt {state.attempt}/{engine.max_retries})...",
            "warning",
        )
        save_state(state)
        return "continue"

    if event.type == EventType.WORKFLOW_COMPLETE:
        return "break"

    # Unknown event - continue
    app.add_activity(f"Unknown event: {event.type.name}", "⚙")
    return "continue"


async def _handle_advance_event(
    app: WorkflowTUIApp,
    engine: WorkflowEngine,
    event: WorkflowEvent,
    config: GalangalConfig,
) -> str:
    """Handle the event from advancing to next stage."""
    state = engine.state

    if event.type == EventType.WORKFLOW_COMPLETE:
        return "break"  # Will be handled in main loop

    if event.type == EventType.STAGE_STARTED:
        # Show skipped stages if any
        skipped = event.data.get("skipped_stages", [])
        for s in skipped:
            app.show_message(f"Skipped {s.value} (condition not met)", "info")

        app.update_stage(state.stage.value, state.attempt)

        # After PM approval, show stage preview
        if event.data.get("show_preview"):
            preview_result = await _show_stage_preview(app, state, config)
            if preview_result == "quit":
                app._workflow_result = "paused"
                return "break"

        return "continue"

    return "continue"


async def _handle_user_interrupts(app: WorkflowTUIApp, engine: WorkflowEngine) -> str:
    """
    Handle user interrupt requests (Ctrl+I, Ctrl+N, Ctrl+B, Ctrl+E).

    Returns:
        "continue" if an interrupt was handled and loop should continue
        "paused" if workflow should pause
        "none" if no interrupt was requested
    """
    state = engine.state

    # Handle interrupt with feedback (Ctrl+I)
    if app._interrupt_requested:
        app.add_activity("Interrupted by user", "⏸️")

        # Get feedback
        feedback = await app.multiline_input_async(
            "What needs to be fixed? (Ctrl+S to submit):", ""
        )

        # Get rollback target
        valid_targets = engine.get_valid_interrupt_targets()
        default_target = engine.get_default_interrupt_target()

        if len(valid_targets) > 1:
            options_text = "\n".join(
                f"  [{i + 1}] {s.value}" + (" (recommended)" if s == default_target else "")
                for i, s in enumerate(valid_targets)
            )
            target_input = await app.text_input_async(
                f"Roll back to which stage?\n\n{options_text}\n\nEnter number:", "1"
            )
            try:
                target_idx = int(target_input or "1") - 1
                target_stage = (
                    valid_targets[target_idx]
                    if 0 <= target_idx < len(valid_targets)
                    else default_target
                )
            except (ValueError, TypeError):
                target_stage = default_target
        else:
            target_stage = valid_targets[0] if valid_targets else state.stage

        # Send action to engine
        result_event = engine.handle_action(
            action(ActionType.INTERRUPT, feedback=feedback or "", target_stage=target_stage)
        )

        app._interrupt_requested = False
        app._paused = False
        app.show_message(
            f"Interrupted - rolling back to {target_stage.value}",
            "warning",
        )
        app.update_stage(state.stage.value, state.attempt)
        return "continue"

    # Handle skip stage (Ctrl+N)
    if app._skip_stage_requested:
        app.add_activity(f"Skipping {state.stage.value} stage", "⏭️")
        skipped_stage = state.stage

        result_event = engine.handle_action(action(ActionType.SKIP))

        if result_event.type == EventType.WORKFLOW_COMPLETE:
            app.show_message("Skipped to COMPLETE", "info")
        else:
            app.show_message(f"Skipped {skipped_stage.value} → {state.stage.value}", "info")
            app.update_stage(state.stage.value, state.attempt)

        app._skip_stage_requested = False
        app._paused = False
        return "continue"

    # Handle back stage (Ctrl+B)
    if app._back_stage_requested:
        current_idx = STAGE_ORDER.index(state.stage)
        if current_idx > 0:
            result_event = engine.handle_action(action(ActionType.BACK))
            app.add_activity(f"Going back to {state.stage.value}", "⏮️")
            app.show_message(f"Back to {state.stage.value}", "info")
            app.update_stage(state.stage.value, state.attempt)
        else:
            app.show_message("Already at first stage", "warning")

        app._back_stage_requested = False
        app._paused = False
        return "continue"

    # Handle manual edit pause (Ctrl+E)
    if app._manual_edit_requested:
        app.add_activity("Paused for manual editing", "✏️")
        app.show_message("Workflow paused - make your edits, then press Enter to continue", "info")

        await app.text_input_async("Press Enter when ready to continue...", "")

        app.add_activity("Resuming workflow", "▶️")
        app.show_message("Resuming...", "info")

        app._manual_edit_requested = False
        app._paused = False
        return "continue"

    return "none"


# =============================================================================
# Lineage staleness checking
# =============================================================================


async def _check_staleness_on_resume(
    app: WorkflowTUIApp,
    state: WorkflowState,
    config: GalangalConfig,
) -> bool:
    """Check for stale stages on resume and prompt user to confirm.

    Detects artifacts modified outside the workflow and stages that need
    to re-run due to upstream changes. Shows a preview and asks for
    confirmation before continuing.

    Args:
        app: TUI application for user interaction.
        state: Current workflow state with lineage information.
        config: Galangal configuration.

    Returns:
        True to continue workflow, False to pause.
    """
    from galangal.core.lineage import LineageTracker, load_task_artifacts

    try:
        tracker = LineageTracker(config.lineage)
        artifacts = load_task_artifacts(state.task_name)

        # Check for external modifications
        mods = tracker.detect_external_mods(state.task_name, artifacts, state)
        if mods:
            app.add_activity("External modifications detected:", "⚠")
            for artifact, sections in mods.items():
                app.add_activity(f"  {artifact}: {', '.join(sections)}", "")

        # Get cascade preview - stages that will re-run
        cascade = tracker.get_cascade_preview(state, artifacts)

        if not cascade and not mods:
            # Everything fresh, continue normally
            return True

        # Build confirmation message
        msg_lines = []

        if mods:
            msg_lines.append("External modifications detected:")
            for artifact, sections in list(mods.items())[:5]:
                msg_lines.append(f"  {artifact}: {', '.join(sections[:3])}")
            msg_lines.append("")

        if cascade:
            msg_lines.append("Stages will re-run due to staleness:")
            for stage_name, reasons in cascade[:5]:
                reason_str = reasons[0] if reasons else "upstream changed"
                msg_lines.append(f"  → {stage_name}: {reason_str}")
            msg_lines.append("")

        msg_lines.append("Continue? (or use --ignore-staleness to skip this check)")

        # Show confirmation
        if config.lineage.block_on_staleness:
            confirmed = await app.ask_yes_no_async("\n".join(msg_lines))
            if not confirmed:
                app.show_message("Workflow paused - staleness not confirmed", "warning")
                return False

            # If user confirms, roll back to earliest stale stage
            if cascade:
                earliest_stale = cascade[0][0]
                current_stage = state.stage.value
                app.add_activity(
                    f"Rolling back from {current_stage} to {earliest_stale} due to staleness",
                    "🔄",
                )
                state.stage = Stage.from_str(earliest_stale)
                state.reset_attempts()
                save_state(state)

        else:
            # Just warn, don't block
            app.add_activity("⚠ Continuing with stale stages", "")

        return True

    except Exception as e:
        # Staleness check failure should not block workflow
        app.add_activity(f"Staleness check failed: {e}", "⚠")
        return True


# =============================================================================
# PM Discovery Q&A functions
# =============================================================================


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

    qa_rounds: list[dict[str, Any]] = state.qa_rounds or []
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
            # AI found no gaps in the brief - continue automatically
            app.show_message("No clarifying questions needed", "success")
            break

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

        app.show_message(
            f"Round {len(qa_rounds)} complete - {len(questions)} Q&As recorded", "success"
        )

        # Ask if user wants more questions
        more_questions = await app.ask_yes_no_async("Got more questions?")
        if not more_questions:
            break

    # Mark discovery complete
    state.qa_complete = True
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
    qa_history: list[dict[str, Any]],
) -> list[str] | None:
    """
    Generate discovery questions by invoking the AI.

    Returns:
        List of questions, empty list if AI found no gaps, or None if failed.
    """
    from galangal.ai import get_backend_with_fallback
    from galangal.config.loader import get_config
    from galangal.ui.tui import TUIAdapter

    prompt = builder.build_discovery_prompt(state, qa_history)
    config = get_config()

    # Log the prompt
    logs_dir = get_task_dir(state.task_name) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    round_num = len(qa_history) + 1
    log_file = logs_dir / f"discovery_{round_num}.log"
    with open(log_file, "w") as f:
        f.write(f"=== Discovery Prompt (Round {round_num}) ===\n{prompt}\n\n")

    # Run AI with fallback support
    backend = get_backend_with_fallback(config.ai.default, config=config)
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
    """Parse questions from AI output.

    The output may be raw JSON stream from Claude CLI, so we first
    extract text content from any JSON lines before parsing.
    """
    import json
    import re

    # First, extract text content from JSON stream if present
    # Only extract from assistant messages - result messages duplicate content
    text_content = []
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Try to parse as JSON (Claude CLI stream format)
        try:
            data = json.loads(line)
            # Extract text from assistant messages only
            # (result messages often duplicate the same content)
            if data.get("type") == "assistant":
                content = data.get("message", {}).get("content", [])
                for item in content:
                    if item.get("type") == "text":
                        text_content.append(item.get("text", ""))
        except (json.JSONDecodeError, TypeError, KeyError):
            # Not JSON, treat as plain text
            text_content.append(line)

    # Join all text content
    full_text = "\n".join(text_content)

    # Check for NO_QUESTIONS marker
    if "# NO_QUESTIONS" in full_text or "#NO_QUESTIONS" in full_text:
        return []

    questions = []
    seen = set()  # Track seen questions to avoid duplicates
    in_questions = False

    for line in full_text.split("\n"):
        line = line.strip()

        # Start capturing after DISCOVERY_QUESTIONS header
        if "DISCOVERY_QUESTIONS" in line:
            in_questions = True
            continue

        # Stop at next header or marker
        if in_questions and line.startswith("#"):
            break

        if in_questions and line:
            # Match numbered questions (1. Question text)
            match = re.match(r"^\d+[\.\)]\s*(.+)$", line)
            if match:
                question = match.group(1).strip()
                # Extract only up to the first question mark (strips trailing explanations)
                question = _extract_question_only(question)
                if question and question not in seen:
                    questions.append(question)
                    seen.add(question)
            elif line.startswith("-"):
                # Also accept bullet points
                question = line[1:].strip()
                question = _extract_question_only(question)
                if question and question not in seen:
                    questions.append(question)
                    seen.add(question)

    return questions


def _extract_question_only(text: str) -> str:
    """
    Extract just the question from text, stripping trailing explanations.

    Handles cases like:
    - "What tech to use? (this is important because...)" -> "What tech to use?"
    - "What tech to use - this affects X and Y" -> "What tech to use"
    - "Since X, what should we do? Because Y..." -> "what should we do?"
    """
    # Find the first question mark
    q_idx = text.find("?")
    if q_idx != -1:
        # Keep everything up to and including the question mark
        return text[: q_idx + 1].strip()

    # No question mark - strip common trailing patterns
    # Strip parenthetical explanations
    paren_idx = text.find("(")
    if paren_idx > 10:  # Only if there's substantial text before
        text = text[:paren_idx].strip()

    # Strip dash-separated explanations
    dash_idx = text.find(" - ")
    if dash_idx > 10:
        text = text[:dash_idx].strip()

    # Strip "because", "since", "as" clauses at the end
    for separator in [" because ", " since ", " as this "]:
        idx = text.lower().find(separator)
        if idx > 10:
            text = text[:idx].strip()

    return text


def _write_discovery_log(task_name: str, qa_rounds: list[dict[str, Any]]) -> None:
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


# =============================================================================
# Helper functions for workflow logic
# =============================================================================


def _build_preflight_error_message(message: str, details: str) -> str:
    """Build error message for preflight failure modal."""
    failed_lines = []
    for line in details.split("\n"):
        if line.strip().startswith("✗") or "Failed" in line or "Missing" in line or "Error" in line:
            failed_lines.append(line.strip())

    modal_message = "Preflight checks failed:\n\n"
    if failed_lines:
        modal_message += "\n".join(failed_lines[:10])
    else:
        modal_message += details[:500]
    modal_message += "\n\nFix issues and retry?"

    return modal_message


def _get_skip_reasons(
    state: WorkflowState,
    config: GalangalConfig,
) -> dict[str, str]:
    """
    Get a mapping of stage names to their skip reasons.

    Checks multiple skip sources in order of precedence:
    1. Task type skips (from TASK_TYPE_SKIP_STAGES)
    2. Config skips (from config.stages.skip)
    3. PM stage plan skips (from STAGE_PLAN.md)
    4. skip_if conditions (glob patterns for conditional stages)

    Args:
        state: Current workflow state with task_type and stage_plan.
        config: Configuration with stages.skip list.

    Returns:
        Dict mapping stage name -> reason string (e.g., "task type: bug_fix")
    """
    skip_reasons: dict[str, str] = {}
    task_type = state.task_type

    # 1. Task type skips
    for stage in TASK_TYPE_SKIP_STAGES.get(task_type, set()):
        skip_reasons[stage.value] = f"task type: {task_type.value}"

    # 2. Config skips
    if config.stages.skip:
        for stage_name in config.stages.skip:
            stage_upper = stage_name.upper()
            if stage_upper not in skip_reasons:
                skip_reasons[stage_upper] = "config: stages.skip"

    # 3. PM stage plan skips
    if state.stage_plan:
        for stage_name, plan_entry in state.stage_plan.items():
            if plan_entry.get("action") == "skip":
                reason = plan_entry.get("reason", "PM recommendation")
                if stage_name not in skip_reasons:
                    skip_reasons[stage_name] = f"PM: {reason}"

    # 4. skip_if conditions for conditional stages
    # Only check stages not already skipped by other means
    conditional_stages = get_conditional_stages()
    runner = ValidationRunner()

    for stage in conditional_stages:
        if stage.value not in skip_reasons:
            if runner.should_skip_stage(stage.value, state.task_name):
                # Get the skip_if pattern for context
                stage_config = getattr(config.validation, stage.value.lower(), None)
                if stage_config and stage_config.skip_if and stage_config.skip_if.no_files_match:
                    patterns = stage_config.skip_if.no_files_match
                    if isinstance(patterns, str):
                        patterns = [patterns]
                    pattern_str = ", ".join(patterns[:2])
                    if len(patterns) > 2:
                        pattern_str += "..."
                    skip_reasons[stage.value] = f"no files match: {pattern_str}"
                else:
                    skip_reasons[stage.value] = "skip_if condition"

    return skip_reasons


async def _show_stage_preview(
    app: WorkflowTUIApp,
    state: WorkflowState,
    config: GalangalConfig,
) -> str:
    """
    Show a preview of stages to run before continuing.

    Displays which stages will run and which will be skipped, with
    annotated reasons for each skip (task type, config, PM plan, skip_if).

    Returns "continue" or "quit".
    """
    # Get all skip reasons (includes skip_if conditions)
    skip_reasons = _get_skip_reasons(state, config)

    # Update hidden stages to include skip_if-based skips
    # This ensures the progress bar reflects the preview
    current_hidden = set(app._hidden_stages)
    new_hidden = current_hidden | set(skip_reasons.keys())
    if new_hidden != current_hidden:
        app.update_hidden_stages(frozenset(new_hidden))

    # Calculate stages to run vs skip
    all_stages = [s for s in STAGE_ORDER if s != Stage.COMPLETE]
    stages_to_run = [s for s in all_stages if s.value not in new_hidden]
    stages_skipped = [s for s in all_stages if s.value in new_hidden]

    # Build preview message
    run_str = " → ".join(s.value for s in stages_to_run)

    # Build annotated skip list
    if stages_skipped:
        skip_lines = []
        for stage in stages_skipped:
            reason = skip_reasons.get(stage.value, "")
            if reason:
                skip_lines.append(f"  {stage.value} ({reason})")
            else:
                skip_lines.append(f"  {stage.value}")
        skip_str = "\n".join(skip_lines)
    else:
        skip_str = "  None"

    # Build a nice preview
    preview = f"""Workflow Preview

Stages to run:
  {run_str}

Skipping:
{skip_str}

Controls during execution:
  ^N Skip stage  ^B Back  ^E Pause for edit  ^I Interrupt"""

    return await app.prompt_async(PromptType.STAGE_PREVIEW, preview)


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


async def _handle_stage_approval(
    app: WorkflowTUIApp,
    state: WorkflowState,
    config: GalangalConfig,
    approval_artifact: str,
) -> bool:
    """
    Handle approval gate after a stage that requires approval.

    Uses prompt_async which automatically races local input vs remote
    responses from the hub, allowing users to approve from either
    the TUI or the Hub UI.

    Args:
        app: TUI application for user interaction.
        state: Current workflow state.
        config: Galangal configuration.
        approval_artifact: Name of the approval artifact to create (e.g., "APPROVAL.md").

    Returns:
        True if workflow should continue, False if rejected/quit.
    """
    default_approver = config.project.approver_name or ""
    stage_name = state.stage.value

    # Notify hub that approval is needed
    from galangal.hub.hooks import notify_approval_needed

    notify_approval_needed(state, state.stage)

    # Send relevant artifacts to hub
    _send_artifacts_for_approval(app, state, stage_name)

    # Prompt for approval (prompt_async handles racing local vs remote)
    prompt_type = PromptType.PLAN_APPROVAL if stage_name == "PM" else PromptType.DESIGN_APPROVAL
    choice = await app.prompt_async(prompt_type, f"Approve {stage_name} to continue?")

    if choice == "yes":
        # Check if this was a remote response from the hub
        remote_data = app._pending_remote_action
        app._pending_remote_action = None  # Clear it
        is_remote = remote_data and remote_data.get("remote")

        if is_remote:
            # Remote approval - use "Hub" as approver
            name = "Hub"
        else:
            # Local approval - prompt for name
            name = await app.text_input_async("Enter approver name:", default_approver)

        if name:
            from galangal.core.utils import now_formatted

            approval_content = f"""# {stage_name} Approval

- **Status:** Approved
- **Approved By:** {name}
- **Date:** {now_formatted()}
"""
            write_artifact(approval_artifact, approval_content, state.task_name)
            app.show_message(f"{stage_name} approved by {name}", "success")

            # PM-specific: Parse and store stage plan
            if state.stage == Stage.PM:
                stage_plan = parse_stage_plan(state.task_name)
                if stage_plan:
                    state.stage_plan = stage_plan
                    save_state(state)
                    # Update progress bar to hide PM-skipped stages
                    skipped = [s for s, v in stage_plan.items() if v["action"] == "skip"]
                    if skipped:
                        new_hidden = set(app._hidden_stages) | set(skipped)
                        app.update_hidden_stages(frozenset(new_hidden))

                # Show stage preview after PM approval
                preview_result = await _show_stage_preview(app, state, config)
                if preview_result == "quit":
                    app._workflow_result = "paused"
                    return False

            return True
        else:
            # Cancelled - ask again
            return await _handle_stage_approval(app, state, config, approval_artifact)

    elif choice == "no":
        # Check for remote text input
        remote_data = app._pending_remote_action
        app._pending_remote_action = None
        is_remote = remote_data and remote_data.get("remote")

        if is_remote and remote_data.get("text_input"):
            # Use remote rejection reason
            reason = remote_data["text_input"]
        elif is_remote:
            # Remote rejection without reason
            reason = "Rejected via Hub"
        else:
            reason = await app.multiline_input_async(
                "Enter rejection reason (Ctrl+S to submit):", "Needs revision"
            )

        if reason:
            state.last_failure = f"{stage_name} rejected: {reason}"
            state.reset_attempts(clear_failure=False)
            save_state(state)
            app.show_message(f"{stage_name} rejected: {reason}", "warning")
            app.show_message(f"Restarting {stage_name} stage with feedback...", "info")
            return False
        else:
            # Cancelled - ask again
            return await _handle_stage_approval(app, state, config, approval_artifact)

    else:  # quit or skip
        app._workflow_result = "paused"
        return False


def _send_artifacts_for_approval(
    app: WorkflowTUIApp,
    state: WorkflowState,
    stage_name: str,
) -> None:
    """Send relevant artifacts to hub for display during approval."""
    try:
        from galangal.core.artifacts import read_artifact
        from galangal.hub.hooks import notify_artifacts_updated

        artifacts: dict[str, str] = {}

        # Send all existing artifacts plus stage-specific ones
        # Core artifacts that may exist at any point
        all_artifacts = [
            "SPEC.md",
            "PLAN.md",
            "STAGE_PLAN.md",
            "DESIGN.md",
            "DEVELOPMENT.md",
            "TEST_REPORT.md",
            "QA_REPORT.md",
            "VALIDATION_REPORT.md",
            "SUMMARY.md",
            "PREFLIGHT_REPORT.md",
        ]

        for name in all_artifacts:
            content = read_artifact(name, state.task_name)
            if content:
                # Truncate very large artifacts
                if len(content) > 50000:
                    content = content[:50000] + "\n\n[... truncated]"
                artifacts[name] = content

        if artifacts:
            notify_artifacts_updated(artifacts)
    except Exception:
        # Artifact sending failure is non-fatal
        pass


async def _handle_workflow_complete(app: WorkflowTUIApp, state: WorkflowState) -> None:
    """Handle workflow completion - finalization and post-completion options."""
    from galangal.core.artifacts import read_artifact

    # Clear fast-track state on completion
    state.clear_fast_track()
    state.clear_passed_stages()
    save_state(state)

    app.show_workflow_complete()
    app.update_stage("COMPLETE")
    app.set_status("complete", "workflow finished")

    # Build completion message with summary if available
    summary_content = read_artifact("SUMMARY.md", state.task_name)
    if summary_content:
        # Truncate if too long for modal display
        summary_preview = summary_content[:2000]
        if len(summary_content) > 2000:
            summary_preview += "\n\n[... truncated]"
        completion_message = f"Workflow complete!\n\n{summary_preview}"
    else:
        completion_message = "Workflow complete!"

    choice = await app.prompt_async(PromptType.COMPLETION, completion_message)

    if choice == "yes":
        # Run finalization
        app.set_status("finalizing", "creating PR...")

        def progress_callback(message: str, status: str) -> None:
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
            # Append to ROLLBACK.md (preserves history from earlier failures)
            from galangal.core.workflow.core import append_rollback_entry

            append_rollback_entry(
                task_name=state.task_name,
                source="Manual review at COMPLETE stage",
                from_stage="COMPLETE",
                target_stage="DEV",
                reason=feedback,
            )
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


async def _init_hub_for_new_task(config: GalangalConfig) -> None:
    """Initialize hub client for new task creation (without existing state)."""
    if not config.hub.enabled:
        return

    try:
        from pathlib import Path

        from galangal.hub.action_handler import get_action_handler
        from galangal.hub.client import HubClient, set_hub_client
        from galangal.hub.hooks import set_main_loop

        # Store main loop for thread-safe async scheduling
        set_main_loop(asyncio.get_running_loop())

        project_path = Path.cwd()
        client = HubClient(
            config=config.hub,
            project_name=config.project.name,
            project_path=project_path,
        )

        # Register action handler
        handler = get_action_handler()
        client.on_action(handler.handle_hub_action)

        # Connect to hub
        connected = await client.connect()
        if connected:
            set_hub_client(client)
            # Send idle state to signal readiness for new task
            await client.send_idle_state()
    except Exception:
        # Hub connection failure is non-fatal
        pass


async def _wait_for_remote_task_create(timeout: float = 0.5) -> Any | None:
    """
    Wait for a CREATE_TASK action from the hub with timeout.

    Args:
        timeout: Maximum seconds to wait.

    Returns:
        PendingTaskCreate if received, None otherwise.
    """
    from galangal.hub.action_handler import get_action_handler

    handler = get_action_handler()
    end_time = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < end_time:
        if handler.has_pending_task_create:
            return handler.get_pending_task_create()
        await asyncio.sleep(0.05)

    return None


def _start_new_task_tui() -> str:
    """
    Create a new task using TUI prompts for task type and description.

    Returns:
        Result string indicating outcome.
    """
    config = get_config()
    app = WorkflowTUIApp("New Task", "SETUP", hidden_stages=frozenset())

    task_info: dict[str, Any] = {
        "type": None,
        "description": None,
        "name": None,
        "github_issue": None,
        "github_repo": None,
        "screenshots": None,
    }

    async def task_creation_loop() -> None:
        """Async task creation flow."""
        # Initialize hub connection for receiving CREATE_TASK actions
        await _init_hub_for_new_task(config)

        try:
            app.add_activity("[bold]Starting new task...[/bold]", "🆕")

            # Check if there's a pending CREATE_TASK from the hub
            pending_task = await _check_for_remote_task_create()
            if pending_task:
                # Use the remote task creation data
                app.add_activity("Received task creation request from Hub", "🌐")
                await _handle_remote_task_create(app, task_info, pending_task)
                return

            # Step 0: Choose task source (manual or GitHub)
            app.set_status("setup", "select task source")
            source_choice = await app.prompt_async(PromptType.TASK_SOURCE, "Create task from:")

            if source_choice == "quit":
                app._workflow_result = "cancelled"
                app.set_timer(0.5, app.exit)
                return

            issue_body_for_screenshots = None

            if source_choice == "github":
                # Handle GitHub issue selection
                app.set_status("setup", "checking GitHub")
                app.show_message("Checking GitHub setup...", "info")

                try:
                    from galangal.github.client import ensure_github_ready
                    from galangal.github.issues import list_issues

                    check = await asyncio.to_thread(ensure_github_ready)
                    if not check:
                        app.show_message("GitHub not ready. Run 'galangal github check'", "error")
                        app._workflow_result = "error"
                        app.set_timer(0.5, app.exit)
                        return

                    task_info["github_repo"] = check.repo_name

                    # List issues with galangal label
                    app.set_status("setup", "fetching issues")
                    app.show_message("Fetching issues...", "info")

                    issues = await asyncio.to_thread(list_issues)
                    if not issues:
                        app.show_message("No issues with 'galangal' label found", "warning")
                        app._workflow_result = "cancelled"
                        app.set_timer(0.5, app.exit)
                        return

                    # Show issue selection
                    app.set_status("setup", "select issue")
                    issue_options = [(i.number, i.title) for i in issues]
                    issue_num = await app.select_github_issue_async(issue_options)

                    if issue_num is None:
                        app._workflow_result = "cancelled"
                        app.set_timer(0.5, app.exit)
                        return

                    # Get the selected issue details
                    selected_issue = next((i for i in issues if i.number == issue_num), None)
                    if selected_issue:
                        task_info["github_issue"] = selected_issue.number
                        task_info["description"] = (
                            f"{selected_issue.title}\n\n{selected_issue.body}"
                        )
                        app.show_message(f"Selected issue #{selected_issue.number}", "success")

                        # Check for screenshots
                        from galangal.github.images import extract_image_urls

                        images = extract_image_urls(selected_issue.body)
                        if images:
                            app.show_message(
                                f"Found {len(images)} screenshot(s) in issue...", "info"
                            )
                            issue_body_for_screenshots = selected_issue.body

                        # Try to infer task type from labels
                        type_hint = selected_issue.get_task_type_hint()
                        if type_hint:
                            task_info["type"] = TaskType.from_str(type_hint)
                            app.show_message(
                                f"Inferred type: {task_info['type'].display_name()}",
                                "info",
                            )

                except Exception as e:
                    from galangal.core.utils import debug_exception

                    debug_exception("GitHub integration failed in new task flow", e)
                    app.show_message(f"GitHub error: {e}", "error")
                    app._workflow_result = "error"
                    app.set_timer(0.5, app.exit)
                    return

            # Step 1: Get task type (if not already set from GitHub labels)
            if task_info["type"] is None:
                app.set_status("setup", "select task type")
                type_choice = await app.prompt_async(PromptType.TASK_TYPE, "Select task type:")

                if type_choice == "quit":
                    app._workflow_result = "cancelled"
                    app.set_timer(0.5, app.exit)
                    return

                # Map selection to TaskType
                task_info["type"] = TaskType.from_str(type_choice)

            app.show_message(f"Task type: {task_info['type'].display_name()}", "success")

            # Step 2: Get task description (if not from GitHub)
            if not task_info["description"]:
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

            # Step 3: Generate task name
            app.set_status("setup", "generating task name")
            from galangal.commands.start import create_task
            from galangal.core.tasks import generate_unique_task_name

            # Use prefix for GitHub issues
            prefix = f"issue-{task_info['github_issue']}" if task_info["github_issue"] else None
            task_info["name"] = await asyncio.to_thread(
                generate_unique_task_name, task_info["description"], prefix
            )
            app.show_message(f"Task name: {task_info['name']}", "info")

            # Step 3.5: Download screenshots if from GitHub issue
            if issue_body_for_screenshots:
                app.set_status("setup", "downloading screenshots")
                try:
                    from galangal.github.issues import download_issue_screenshots

                    task_dir = get_task_dir(task_info["name"])
                    screenshot_paths = await asyncio.to_thread(
                        download_issue_screenshots,
                        issue_body_for_screenshots,
                        task_dir,
                    )
                    if screenshot_paths:
                        task_info["screenshots"] = screenshot_paths
                        app.show_message(
                            f"Downloaded {len(screenshot_paths)} screenshot(s)",
                            "success",
                        )
                except Exception as e:
                    from galangal.core.utils import debug_exception

                    debug_exception("Screenshot download failed", e)
                    app.show_message(f"Screenshot download failed: {e}", "warning")
                    # Non-critical - continue without screenshots

            # Step 4: Create the task
            app.set_status("setup", "creating task")
            success, message = await asyncio.to_thread(
                create_task,
                task_info["name"],
                task_info["description"],
                task_info["type"],
                task_info["github_issue"],
                task_info["github_repo"],
                task_info["screenshots"],
            )

            if success:
                app.show_message(message, "success")
                app._workflow_result = "task_created"

                # Mark issue as in-progress if from GitHub
                if task_info["github_issue"]:
                    try:
                        from galangal.github.issues import mark_issue_in_progress

                        await asyncio.to_thread(mark_issue_in_progress, task_info["github_issue"])
                        app.show_message("Marked issue as in-progress", "info")
                    except Exception as e:
                        from galangal.core.utils import debug_exception

                        debug_exception("Failed to mark issue as in-progress", e)
                        # Non-critical - continue anyway
            else:
                app.show_error("Task creation failed", message)
                app._workflow_result = "error"

        except Exception as e:
            from galangal.core.utils import debug_exception

            debug_exception("Task creation failed in new task flow", e)
            app.show_error("Task creation error", str(e))
            app._workflow_result = "error"
        finally:
            # Cleanup hub client
            await _cleanup_hub_client()
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


async def _check_for_remote_task_create() -> Any | None:
    """
    Check if there's a pending CREATE_TASK action from the hub.

    Returns:
        PendingTaskCreate if available, None otherwise.
    """
    from galangal.hub.action_handler import get_action_handler

    handler = get_action_handler()
    if handler.has_pending_task_create:
        return handler.get_pending_task_create()
    return None


async def _handle_remote_task_create(
    app: WorkflowTUIApp,
    task_info: dict[str, Any],
    pending_task: Any,
) -> None:
    """
    Handle task creation from a remote CREATE_TASK action.

    Args:
        app: TUI application for status updates.
        task_info: Dict to populate with task details.
        pending_task: PendingTaskCreate with the remote data.
    """
    from galangal.commands.start import create_task
    from galangal.core.tasks import generate_unique_task_name

    try:
        # Extract data from pending task
        task_info["github_issue"] = pending_task.github_issue
        task_info["github_repo"] = pending_task.github_repo

        # Determine task type
        task_type_str = pending_task.task_type or "feature"
        task_info["type"] = TaskType.from_str(task_type_str)

        # Get description from either manual input or GitHub issue
        if pending_task.github_issue:
            app.set_status("setup", "fetching GitHub issue")
            app.show_message(
                f"Creating task from GitHub issue #{pending_task.github_issue}...",
                "info",
            )

            # Fetch issue details
            from galangal.github.client import ensure_github_ready
            from galangal.github.issues import get_issue

            check = await asyncio.to_thread(ensure_github_ready)
            if check:
                task_info["github_repo"] = pending_task.github_repo or check.repo_name

            issue = await asyncio.to_thread(get_issue, pending_task.github_issue)
            if issue:
                task_info["description"] = f"{issue.title}\n\n{issue.body}"
                app.show_message(f"Issue #{issue.number}: {issue.title}", "info")

                # Try to infer task type from labels if not specified
                if not pending_task.task_type:
                    type_hint = issue.get_task_type_hint()
                    if type_hint:
                        task_info["type"] = TaskType.from_str(type_hint)

                # Check for screenshots
                from galangal.github.images import extract_image_urls

                images = extract_image_urls(issue.body)
                issue_body_for_screenshots = issue.body if images else None
            else:
                app.show_message(f"Could not fetch issue #{pending_task.github_issue}", "warning")
                task_info["description"] = pending_task.task_description or ""
                issue_body_for_screenshots = None
        else:
            # Manual task creation
            task_info["description"] = pending_task.task_description or ""
            issue_body_for_screenshots = None

        if not task_info["description"]:
            app.show_message("No task description provided", "error")
            app._workflow_result = "error"
            return

        app.show_message(f"Task type: {task_info['type'].display_name()}", "success")

        # Generate task name
        app.set_status("setup", "generating task name")
        prefix = f"issue-{task_info['github_issue']}" if task_info["github_issue"] else None
        task_info["name"] = pending_task.task_name or await asyncio.to_thread(
            generate_unique_task_name, task_info["description"], prefix
        )
        app.show_message(f"Task name: {task_info['name']}", "info")

        # Download screenshots if from GitHub issue
        if issue_body_for_screenshots:
            app.set_status("setup", "downloading screenshots")
            try:
                from galangal.github.issues import download_issue_screenshots

                task_dir = get_task_dir(task_info["name"])
                screenshot_paths = await asyncio.to_thread(
                    download_issue_screenshots,
                    issue_body_for_screenshots,
                    task_dir,
                )
                if screenshot_paths:
                    task_info["screenshots"] = screenshot_paths
                    app.show_message(
                        f"Downloaded {len(screenshot_paths)} screenshot(s)",
                        "success",
                    )
            except Exception as e:
                from galangal.core.utils import debug_exception

                debug_exception("Screenshot download failed", e)
                app.show_message(f"Screenshot download failed: {e}", "warning")

        # Create the task
        app.set_status("setup", "creating task")
        success, message = await asyncio.to_thread(
            create_task,
            task_info["name"],
            task_info["description"],
            task_info["type"],
            task_info["github_issue"],
            task_info["github_repo"],
            task_info["screenshots"],
        )

        if success:
            app.show_message(message, "success")
            app._workflow_result = "task_created"

            # Mark issue as in-progress if from GitHub
            if task_info["github_issue"]:
                try:
                    from galangal.github.issues import mark_issue_in_progress

                    await asyncio.to_thread(mark_issue_in_progress, task_info["github_issue"])
                    app.show_message("Marked issue as in-progress", "info")
                except Exception:
                    pass  # Non-critical
        else:
            app.show_error("Task creation failed", message)
            app._workflow_result = "error"

    except Exception as e:
        from galangal.core.utils import debug_exception

        debug_exception("Remote task creation failed", e)
        app.show_error("Task creation error", str(e))
        app._workflow_result = "error"
    finally:
        # Cleanup hub client
        await _cleanup_hub_client()
        app.set_timer(0.5, app.exit)
