"""
Headless workflow runner for daemon/agent mode.

Runs the workflow engine without a Textual TUI, suitable for:
- Hub agent daemon (galangal run)
- Background/headless execution
- Environments without a TTY

Output and prompts are routed to the hub via the existing hook system.
Approval gates send prompts to the hub UI and wait for responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from galangal.config.loader import get_config
from galangal.config.schema import GalangalConfig
from galangal.core.state import Stage, WorkflowState, save_state
from galangal.core.workflow.engine import (
    ActionType,
    EventType,
    WorkflowEngine,
    WorkflowEvent,
    action,
)

logger = logging.getLogger(__name__)


class HeadlessApp:
    """
    Stub TUI app for headless execution.

    Routes activity and messages to hub output hooks so they appear
    in the live output stream on the hub dashboard.
    """

    def __init__(self) -> None:
        self._paused = False
        self._workflow_result: str | None = None
        self._interrupt_requested = False
        self._skip_requested = False
        self._back_requested = False
        self._edit_requested = False

    def add_activity(self, activity: str, icon: str = "•", **kwargs: Any) -> None:
        """Route activity to hub output."""
        from galangal.hub.hooks import notify_output
        notify_output(f"{icon} {activity}", "activity")

    def show_message(self, message: str, style: str = "info", **kwargs: Any) -> None:
        """Route message to hub output."""
        from galangal.hub.hooks import notify_output
        line_type = "error" if style == "error" else "activity"
        notify_output(f"[{style}] {message}", line_type)

    def update_stage(self, stage: str, attempt: int = 1) -> None:
        """No-op for headless mode."""
        pass

    def set_status(self, status: str, message: str = "") -> None:
        """No-op for headless mode."""
        pass

    def clear_error(self) -> None:
        """No-op for headless mode."""
        pass

    def show_error(self, title: str, message: str = "") -> None:
        """Route error to hub output."""
        from galangal.hub.hooks import notify_output
        notify_output(f"ERROR: {title} - {message}", "error")

    def show_stage_complete(self, stage: str, success: bool, duration: int | None = None) -> None:
        """Route stage completion to hub output."""
        from galangal.hub.hooks import notify_output
        status = "completed" if success else "failed"
        dur_str = f" ({duration}s)" if duration else ""
        notify_output(f"Stage {stage} {status}{dur_str}", "activity")

    def update_stage_durations(self, durations: dict[str, int]) -> None:
        """No-op for headless mode."""
        pass

    def update_backend_progress(
        self,
        turns: int = 0,
        max_turns: int = 0,
        lines: int = 0,
        summary: str = "",
    ) -> None:
        """No-op for headless mode."""
        pass

    def add_raw_line(self, line: str) -> None:
        """Route raw output line to hub."""
        from galangal.hub.hooks import notify_output
        notify_output(line, "raw")

    def add_file(self, action: str, path: str) -> None:
        """No-op for headless mode."""
        pass

    def set_turns(self, turns: int) -> None:
        """No-op for headless mode."""
        pass

    def show_file_change(self, action: str, path: str) -> None:
        """No-op for headless mode."""
        pass

    def show_workflow_complete(self) -> None:
        """Route completion to hub output."""
        from galangal.hub.hooks import notify_output
        notify_output("Workflow complete!", "activity")


async def run_workflow_headless(
    state: WorkflowState,
    ignore_staleness: bool = False,
) -> str:
    """
    Run the workflow headlessly within an existing async event loop.

    This is the main entry point for daemon/agent mode execution.
    The hub client should already be connected and set as the global client.

    Args:
        state: Current workflow state.
        ignore_staleness: If True, skip lineage staleness checks.

    Returns:
        Result string: "done", "paused", or "error".
    """
    from galangal.hub.hooks import (
        notify_output,
        notify_stage_start,
        notify_state_saved,
        notify_task_complete,
    )

    config = get_config()
    engine = WorkflowEngine(state, config)
    app = HeadlessApp()
    # Per-stage peer-review auto-accept loop counters (persist across iterations).
    peer_review_loops: dict[str, int] = {}

    notify_output(f"Starting workflow for task: {state.task_name}", "activity")
    notify_output(f"Current stage: {state.stage.value}", "activity")

    # One-time startup checks (mid-stage crash marker, dirty working tree).
    from galangal.core.workflow.core import workflow_startup_checks

    for warning in workflow_startup_checks(state):
        notify_output(warning, "activity")

    try:
        while not engine.is_complete and not app._paused:
            # Check GitHub issue status
            github_event = await asyncio.to_thread(engine.check_github_issue)
            if github_event:
                notify_output(
                    f"GitHub issue #{state.github_issue} closed - pausing", "activity"
                )
                return "paused"

            notify_output(f"Executing stage: {engine.current_stage.value}", "activity")
            notify_stage_start(state, engine.current_stage)

            # Start stage timer
            engine.start_stage_timer()

            # Headless PM discovery: there is no interactive user, so generate
            # clarifying questions and answer them from the brief (issue body +
            # comments) via the AI, instead of dropping discovery entirely.
            if engine.current_stage == Stage.PM and not state.qa_complete:
                await asyncio.to_thread(_run_headless_discovery, state)

            # Execute stage in thread (it's blocking)
            workflow_event = await asyncio.to_thread(
                engine.execute_current_stage,
                app,
                lambda: app._paused,
            )

            # Notify hub of state change
            notify_state_saved(state)

            # Handle the event
            result = await _handle_event_headless(
                app, engine, workflow_event, config, peer_review_loops
            )
            if result == "break":
                break
            # "continue" → loop again

        if engine.is_complete:
            notify_task_complete(state, success=True)
            notify_output("Workflow completed successfully!", "activity")
            return "done"

        return app._workflow_result or "paused"

    except Exception as e:
        logger.exception(f"Headless workflow error: {e}")
        notify_output(f"Workflow error: {e}", "error")
        notify_task_complete(state, success=False)
        # The task failed terminally (not a pause/resume): hand the issue back to
        # the pickup queue so it isn't stranded with an "in-progress" label.
        _restore_issue_on_failure(state)
        return "error"


def _run_headless_discovery(state: WorkflowState) -> None:
    """Generate and AI-answer PM discovery questions for a headless run.

    Mirrors the interactive Q&A, but with no user: the brief (which for issue
    runs now includes the issue body and comment thread) is used to answer the
    model's own clarifying questions, and the result is written to
    DISCOVERY_LOG.md so PM can incorporate it. Always marks discovery complete
    so the run can never deadlock; on any failure it degrades to a plain skip.
    """
    import re

    from galangal.core.workflow.tui_runner import _parse_discovery_questions, _write_discovery_log
    from galangal.hub.hooks import notify_output
    from galangal.prompts.builder import PromptBuilder

    try:
        config = get_config()

        # Respect a per-task-type opt-out (same as the interactive path).
        tt_settings = config.task_type_settings.get(state.task_type.value)
        if tt_settings and getattr(tt_settings, "skip_discovery", False):
            notify_output("Discovery skipped for this task type", "activity")
            return

        from galangal.ai import get_backend_with_fallback

        backend = get_backend_with_fallback(config.ai.default, config=config)
        builder = PromptBuilder()

        # 1. Generate clarifying questions.
        q_prompt = builder.build_discovery_prompt(state, [])
        q_text = backend.generate_text(q_prompt, timeout=300)
        questions = _parse_discovery_questions(q_text or "")
        if not questions:
            notify_output("Discovery: no clarifying questions needed", "activity")
            return

        notify_output(f"Discovery: answering {len(questions)} questions from the brief", "activity")

        # 2. Answer them from the brief.
        numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
        a_prompt = (
            "Answer these clarifying questions about a development task using ONLY "
            "the brief below. Be concise. If the brief does not specify something, "
            "pick a sensible default and note it briefly.\n\n"
            f"Brief:\n{state.task_description}\n\n"
            f"Questions:\n{numbered}\n\n"
            "Output a numbered list of answers matching the question numbers, one "
            "answer per line. Output only the list."
        )
        a_text = backend.generate_text(a_prompt, timeout=300) or ""

        # 3. Parse answers aligned to questions (pad any the model skipped).
        parsed: dict[int, str] = {}
        for line in a_text.splitlines():
            m = re.match(r"^\s*(\d+)[.)]\s*(.+)$", line.strip())
            if m:
                parsed[int(m.group(1))] = m.group(2).strip()
        answers = [
            parsed.get(i + 1, "Not specified in the brief; use best engineering judgment.")
            for i in range(len(questions))
        ]

        qa_rounds = [{"questions": questions, "answers": answers}]
        state.qa_rounds = qa_rounds
        _write_discovery_log(state.task_name, qa_rounds)
        notify_output("Discovery: wrote DISCOVERY_LOG.md", "activity")
    except Exception:
        logger.debug("Headless discovery failed; proceeding without it", exc_info=True)
    finally:
        # Never block a headless run on discovery.
        state.qa_complete = True
        save_state(state)


def _restore_issue_on_failure(state: WorkflowState) -> None:
    """Best-effort: return a linked issue to the pickup queue on terminal failure.

    Only meaningful for issue-linked tasks; a no-op otherwise. Never raises — a
    label-restore failure must not mask the original workflow error.
    """
    if not state.github_issue:
        return
    try:
        from galangal.github.issues import restore_issue_to_pickup

        restore_issue_to_pickup(state.github_issue)
    except Exception:
        logger.debug("Failed to restore issue label on failure", exc_info=True)


async def _handle_event_headless(
    app: HeadlessApp,
    engine: WorkflowEngine,
    event: WorkflowEvent,
    config: GalangalConfig,
    peer_review_loops: dict[str, int] | None = None,
) -> str:
    """
    Handle a workflow event in headless mode.

    For approval gates, sends prompts to the hub and waits for responses.
    For failures, auto-retries up to max_retries.

    Returns:
        "continue" to loop again, "break" to exit.
    """
    from galangal.hub.hooks import (
        notify_output,
        notify_stage_complete,
        notify_stage_fail,
    )

    state = engine.state

    if event.type == EventType.WORKFLOW_PAUSED:
        app._workflow_result = "paused"
        return "break"

    if event.type == EventType.STAGE_COMPLETED:
        duration = state.record_stage_duration()
        app.show_stage_complete(state.stage.value, True, duration)
        notify_stage_complete(state, state.stage)

        # Advance to next stage
        advance_event = engine.handle_action(
            action(ActionType.CONTINUE), tui_app=app
        )
        return _handle_advance_headless(app, engine, advance_event)

    if event.type == EventType.PEER_REVIEW_REQUIRED:
        return await _handle_peer_review_headless(
            app, engine, config, peer_review_loops if peer_review_loops is not None else {}
        )

    if event.type == EventType.APPROVAL_REQUIRED:
        artifact_name = event.data.get("artifact_name", "APPROVAL.md")
        notify_output(f"Approval required for {state.stage.value}", "activity")

        # Send prompt to hub and wait for response
        response = await _wait_for_hub_approval(state, artifact_name)

        if response == "approve":
            # Write approval artifact
            from galangal.core.artifacts import write_artifact
            write_artifact(artifact_name, "APPROVED", state.task_name)
            notify_output(f"Stage {state.stage.value} approved", "activity")

            advance_event = engine.handle_action(
                action(ActionType.CONTINUE), tui_app=app
            )
            return _handle_advance_headless(app, engine, advance_event)
        elif response == "reject":
            notify_output(f"Stage {state.stage.value} rejected, re-running", "activity")
            return "continue"
        else:
            # Quit/pause
            save_state(state)
            app._workflow_result = "paused"
            return "break"

    if event.type == EventType.STAGE_FAILED:
        app.show_stage_complete(state.stage.value, False)
        notify_stage_fail(state, state.stage, event.message or "Stage failed")
        notify_output(
            f"Retrying (attempt {state.attempt}/{engine.max_retries})...",
            "activity",
        )
        save_state(state)
        return "continue"

    if event.type == EventType.MAX_RETRIES_EXCEEDED:
        app.show_stage_complete(state.stage.value, False)
        notify_output(
            f"Max retries exceeded for {state.stage.value}", "error"
        )

        # Send prompt to hub for user decision
        response = await _wait_for_hub_decision(
            state,
            f"Stage {state.stage.value} failed after {engine.max_retries} attempts.\n\n"
            f"Error: {event.message}",
            prompt_type="STAGE_FAILURE",
            options=[
                {"key": "retry", "label": "Retry", "result": "retry"},
                {"key": "quit", "label": "Pause workflow", "result": "quit"},
            ],
        )

        if response == "retry":
            state.reset_attempts()
            save_state(state)
            return "continue"
        else:
            save_state(state)
            app._workflow_result = "paused"
            return "break"

    if event.type == EventType.PREFLIGHT_FAILED:
        app.show_stage_complete(state.stage.value, False)
        notify_output(f"Preflight failed: {event.message}", "error")

        response = await _wait_for_hub_decision(
            state,
            f"Preflight checks failed:\n{event.message}",
            prompt_type="PREFLIGHT_RETRY",
            options=[
                {"key": "retry", "label": "Retry", "result": "retry"},
                {"key": "quit", "label": "Pause workflow", "result": "quit"},
            ],
        )

        if response == "retry":
            return "continue"
        else:
            save_state(state)
            app._workflow_result = "paused"
            return "break"

    if event.type == EventType.CLARIFICATION_REQUIRED:
        app.show_stage_complete(state.stage.value, False)
        questions = event.data.get("questions", [])
        notify_output(
            f"Clarification needed ({len(questions)} questions) - pausing",
            "activity",
        )
        save_state(state)
        app._workflow_result = "paused"
        return "break"

    if event.type == EventType.USER_DECISION_REQUIRED:
        app.show_stage_complete(state.stage.value, False)
        notify_output(
            f"User decision required for {state.stage.value} - auto-approving",
            "activity",
        )
        # Auto-approve decisions in headless mode
        result_event = engine.handle_user_decision("approve", tui_app=app)
        if result_event.type == EventType.WORKFLOW_COMPLETE:
            return "break"
        return "continue"

    if event.type == EventType.ROLLBACK_TRIGGERED:
        target = event.data.get("to_stage")
        notify_output(
            f"Rolling back to {target.value if target else 'unknown'}: {event.message}",
            "activity",
        )
        return "continue"

    if event.type == EventType.BUDGET_EXCEEDED:
        notify_output(event.message, "error")
        response = await _wait_for_hub_decision(
            state,
            f"{event.message}\n\nContinue (disables the budget check for this "
            "task) or pause?",
            prompt_type="BUDGET_EXCEEDED",
            options=[
                {"key": "continue", "label": "Continue", "result": "continue"},
                {"key": "quit", "label": "Pause workflow", "result": "quit"},
            ],
        )
        if response == "continue":
            state.budget_ack = True
            save_state(state)
            return "continue"
        save_state(state)
        app._workflow_result = "paused"
        return "break"

    if event.type == EventType.ROLLBACK_BLOCKED:
        notify_output(f"Rollback blocked: {event.message}", "error")
        save_state(state)
        app._workflow_result = "paused"
        return "break"

    if event.type == EventType.WORKFLOW_COMPLETE:
        return "break"

    # Unknown event
    notify_output(f"Unknown event: {event.type.name}", "activity")
    return "continue"


def _handle_advance_headless(
    app: HeadlessApp,
    engine: WorkflowEngine,
    event: WorkflowEvent,
) -> str:
    """Handle the event from advancing to next stage."""
    if event.type == EventType.WORKFLOW_COMPLETE:
        return "break"

    if event.type == EventType.STAGE_STARTED:
        skipped = event.data.get("skipped_stages", [])
        for s in skipped:
            from galangal.hub.hooks import notify_output
            notify_output(f"Skipped {s.value}", "activity")
        return "continue"

    return "continue"


async def _handle_peer_review_headless(
    app: HeadlessApp,
    engine: WorkflowEngine,
    config: GalangalConfig,
    peer_review_loops: dict[str, int],
) -> str:
    """Run peer review in headless mode.

    There is no interactive user, so only the auto-accept path is available:
    on REQUEST_CHANGES the stage re-runs with the reviewer's feedback, up to
    ``max_auto_loops`` times. If the reviewer still disagrees after that (or
    auto-accept is disabled), the workflow proceeds with the stage as-is rather
    than deadlocking. If the reviewer backend is unavailable, ``execute_peer_review``
    degrades to APPROVE and the workflow continues normally.
    """
    from galangal.hub.hooks import notify_output

    stage = engine.state.stage
    pr_config = config.peer_review

    notify_output(f"Peer review: reviewing {stage.value}...", "activity")
    decision, notes = await asyncio.to_thread(engine.execute_peer_review, app)

    if decision == "APPROVE":
        notify_output("Peer review: APPROVED", "activity")
        peer_review_loops.pop(stage.value, None)
        advance_event = engine.handle_action(action(ActionType.CONTINUE), tui_app=app)
        return _handle_advance_headless(app, engine, advance_event)

    # REQUEST_CHANGES
    loop_count = peer_review_loops.get(stage.value, 0)
    if pr_config.auto_accept and loop_count < pr_config.max_auto_loops:
        peer_review_loops[stage.value] = loop_count + 1
        notify_output(
            f"Peer review: REQUEST_CHANGES - re-running {stage.value} with feedback "
            f"(loop {loop_count + 1}/{pr_config.max_auto_loops})",
            "activity",
        )
        engine.accept_peer_review_feedback(notes)
        return "continue"  # re-run the same stage with the feedback queued

    # Auto-accept exhausted or disabled, and there is no user to consult.
    notify_output(
        f"Peer review unresolved for {stage.value} after {loop_count} loop(s); "
        "proceeding (headless: no user to consult)",
        "activity",
    )
    peer_review_loops.pop(stage.value, None)
    advance_event = engine.handle_action(action(ActionType.CONTINUE), tui_app=app)
    return _handle_advance_headless(app, engine, advance_event)


async def _wait_for_hub_approval(
    state: WorkflowState,
    artifact_name: str,
    timeout: float = 3600,
) -> str:
    """
    Send approval prompt to hub and wait for response.

    Args:
        state: Current workflow state.
        artifact_name: Name of the approval artifact.
        timeout: Max seconds to wait.

    Returns:
        "approve", "reject", or "quit".
    """
    from galangal.hub.hooks import notify_prompt, notify_prompt_cleared

    # Send prompt to hub
    notify_prompt(
        prompt_type="APPROVAL",
        message=f"Stage {state.stage.value} needs approval.\n\nReview the artifacts and approve or reject.",
        options=[
            {"key": "approve", "label": "Approve", "result": "approve", "color": "green"},
            {"key": "reject", "label": "Reject & Redo", "result": "reject", "color": "red"},
            {"key": "quit", "label": "Pause", "result": "quit"},
        ],
        artifacts=[artifact_name],
        context={
            "stage": state.stage.value,
            "task_name": state.task_name,
        },
    )

    try:
        result = await _poll_for_response(timeout)
        return result
    finally:
        notify_prompt_cleared()


async def _wait_for_hub_decision(
    state: WorkflowState,
    message: str,
    prompt_type: str,
    options: list[dict],
    timeout: float = 3600,
) -> str:
    """Send a decision prompt to hub and wait for response."""
    from galangal.hub.hooks import notify_prompt, notify_prompt_cleared

    notify_prompt(
        prompt_type=prompt_type,
        message=message,
        options=[
            {"key": o["key"], "label": o["label"], "result": o["result"]}
            for o in options
        ],
        context={
            "stage": state.stage.value,
            "task_name": state.task_name,
        },
    )

    try:
        result = await _poll_for_response(timeout)
        return result
    finally:
        notify_prompt_cleared()


async def _poll_for_response(timeout: float = 3600) -> str:
    """
    Poll the action handler for a response from the hub.

    Returns the response result string, or "quit" on timeout.
    """
    from galangal.hub.action_handler import get_action_handler

    handler = get_action_handler()
    elapsed = 0.0
    interval = 0.5

    while elapsed < timeout:
        response = handler.get_pending_response()
        if response:
            return response.result

        await asyncio.sleep(interval)
        elapsed += interval

    return "quit"  # Timeout → pause
