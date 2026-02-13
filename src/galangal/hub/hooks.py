"""
Hooks for hub integration.

These hooks are called at key points in the workflow to sync state
and events with the hub server.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from galangal.core.state import Stage, WorkflowState

from galangal.hub.client import EventType, get_hub_client

# Store reference to the main event loop for thread-safe scheduling
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Set the main event loop for thread-safe async scheduling."""
    global _main_loop
    _main_loop = loop


def _schedule_async(coro: Coroutine[Any, Any, Any]) -> None:
    """
    Schedule an async coroutine in a thread-safe manner.

    Works whether called from the main thread (with event loop) or
    from a background thread (e.g., inside asyncio.to_thread).
    """
    try:
        # Try to get the running loop (works if we're in async context)
        loop = asyncio.get_running_loop()
        asyncio.create_task(coro)
    except RuntimeError:
        # No running loop - we're in a thread
        # Use the stored main loop or try to get one
        loop = _main_loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            # Can't schedule - silently skip (hub is optional)
            # Close the coroutine to avoid warning
            coro.close()


def notify_state_saved(state: WorkflowState) -> None:
    """
    Notify hub that state was saved.

    Called after save_state() completes successfully.

    Args:
        state: The workflow state that was saved.
    """
    client = get_hub_client()
    if client and client.connected:
        # Run async in background (thread-safe)
        _schedule_async(_send_state_update(state))
        _schedule_async(_send_task_artifacts_snapshot(state.task_name))


async def _send_state_update(state: WorkflowState) -> None:
    """Send state update to hub."""
    client = get_hub_client()
    if client:
        await client.send_state(state)


def _load_task_artifacts_snapshot(task_name: str) -> dict[str, str]:
    """Load all present task artifacts from DB for hub display."""
    try:
        from galangal.core.task_index import TaskIndex

        index = TaskIndex()
        artifacts: dict[str, str] = {}
        for name in index.list_task_artifacts(task_name=task_name):
            content = index.read_artifact(task_name=task_name, name=name)
            if content is None:
                continue
            if len(content) > 50000:
                content = content[:50000] + "\n\n[... truncated]"
            artifacts[name] = content
        return artifacts
    except Exception:
        return {}


async def _send_task_artifacts_snapshot(task_name: str) -> None:
    """Send latest DB-backed artifacts for task to hub."""
    client = get_hub_client()
    if not client:
        return
    artifacts = _load_task_artifacts_snapshot(task_name)
    await client.send_artifacts(artifacts, replace=True, task_name=task_name)


def notify_stage_start(state: WorkflowState, stage: Stage) -> None:
    """
    Notify hub that a stage is starting.

    Args:
        state: Current workflow state.
        stage: The stage that is starting.
    """
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(
            _send_event(
                EventType.STAGE_START,
                {
                    "task_name": state.task_name,
                    "stage": stage.value,
                    "attempt": state.attempt,
                },
            )
        )


def notify_stage_complete(state: WorkflowState, stage: Stage) -> None:
    """
    Notify hub that a stage completed successfully.

    Args:
        state: Current workflow state.
        stage: The stage that completed.
    """
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(
            _send_event(
                EventType.STAGE_COMPLETE,
                {
                    "task_name": state.task_name,
                    "stage": stage.value,
                    "duration": state.get_stage_duration(stage),
                },
            )
        )


def notify_stage_fail(state: WorkflowState, stage: Stage, error: str) -> None:
    """
    Notify hub that a stage failed.

    Args:
        state: Current workflow state.
        stage: The stage that failed.
        error: Error message.
    """
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(
            _send_event(
                EventType.STAGE_FAIL,
                {
                    "task_name": state.task_name,
                    "stage": stage.value,
                    "error": error[:500],  # Truncate for transmission
                    "attempt": state.attempt,
                },
            )
        )


def notify_approval_needed(state: WorkflowState, stage: Stage) -> None:
    """
    Notify hub that approval is needed.

    Args:
        state: Current workflow state.
        stage: The stage awaiting approval.
    """
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(
            _send_event(
                EventType.APPROVAL_NEEDED,
                {
                    "task_name": state.task_name,
                    "stage": stage.value,
                },
            )
        )


def notify_rollback(state: WorkflowState, from_stage: Stage, to_stage: Stage, reason: str) -> None:
    """
    Notify hub that a rollback occurred.

    Args:
        state: Current workflow state.
        from_stage: Stage that triggered the rollback.
        to_stage: Target stage of the rollback.
        reason: Reason for the rollback.
    """
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(
            _send_event(
                EventType.ROLLBACK,
                {
                    "task_name": state.task_name,
                    "from_stage": from_stage.value,
                    "to_stage": to_stage.value,
                    "reason": reason[:500],
                },
            )
        )


def notify_task_complete(state: WorkflowState, success: bool) -> None:
    """
    Notify hub that a task completed.

    Args:
        state: Final workflow state.
        success: Whether the task completed successfully.
    """
    client = get_hub_client()
    if client and client.connected:
        event_type = EventType.TASK_COMPLETE if success else EventType.TASK_ERROR
        _schedule_async(
            _send_event(
                event_type,
                {
                    "task_name": state.task_name,
                    "final_stage": state.stage.value,
                    "success": success,
                },
            )
        )


async def _send_event(event_type: EventType, data: dict) -> None:
    """Send an event to hub."""
    client = get_hub_client()
    if client:
        await client.send_event(event_type, data)


def notify_prompt(
    prompt_type: str,
    message: str,
    options: list,
    artifacts: list[str] | None = None,
    context: dict | None = None,
    questions: list[str] | None = None,
) -> None:
    """
    Notify hub that a prompt is being displayed.

    Args:
        prompt_type: Type of prompt (e.g., "PLAN_APPROVAL", "COMPLETION").
        message: Message being displayed.
        options: List of PromptOption objects or dicts.
        artifacts: List of artifact names relevant to this prompt.
        context: Optional additional context.
        questions: List of questions for Q&A style prompts.
    """
    client = get_hub_client()
    if client and client.connected:
        # Convert PromptOption objects to dicts if needed
        option_dicts = []
        for opt in options:
            if hasattr(opt, "key"):
                # It's a PromptOption object
                option_dicts.append({
                    "key": opt.key,
                    "label": opt.label,
                    "result": opt.result,
                    "color": getattr(opt, "color", None),
                })
            else:
                # It's already a dict
                option_dicts.append(opt)

        _schedule_async(
            _send_prompt(prompt_type, message, option_dicts, artifacts, context, questions)
        )


async def _send_prompt(
    prompt_type: str,
    message: str,
    options: list[dict],
    artifacts: list[str] | None,
    context: dict | None,
    questions: list[str] | None,
) -> None:
    """Send prompt to hub."""
    client = get_hub_client()
    if client:
        await client.send_prompt(prompt_type, message, options, artifacts, context, questions)


def notify_prompt_cleared() -> None:
    """Notify hub that the current prompt has been answered/cleared."""
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(_clear_prompt())


async def _clear_prompt() -> None:
    """Clear prompt on hub."""
    client = get_hub_client()
    if client:
        await client.clear_prompt()


def notify_artifacts_updated(artifacts: dict[str, str]) -> None:
    """
    Notify hub of artifact content updates.

    Args:
        artifacts: Dict mapping artifact names to content.
    """
    client = get_hub_client()
    if client and client.connected:
        _schedule_async(_send_artifacts(artifacts))


async def _send_artifacts(artifacts: dict[str, str]) -> None:
    """Send artifacts to hub."""
    client = get_hub_client()
    if client:
        await client.send_artifacts(artifacts)


def _resolve_active_task_name() -> str | None:
    """Best-effort active task lookup for DB log persistence."""
    try:
        from galangal.core.tasks import get_active_task

        return get_active_task()
    except Exception:
        return None


def notify_output(line: str, line_type: str = "raw", task_name: str | None = None) -> None:
    """
    Notify hub of CLI output.

    Args:
        line: The output line content.
        line_type: Type of line (raw, activity, tool, error).
        task_name: Optional explicit task name for DB log persistence.
    """
    resolved_task_name = task_name or _resolve_active_task_name()
    if resolved_task_name and line:
        try:
            from galangal.core.task_index import TaskIndex

            TaskIndex().append_task_log_line(
                task_name=resolved_task_name,
                line=line.rstrip("\n"),
                line_type=line_type,
            )
        except Exception:
            pass

    client = get_hub_client()
    if client and client.connected:
        _schedule_async(_send_output(line, line_type))


async def _send_output(line: str, line_type: str) -> None:
    """Send output line to hub."""
    client = get_hub_client()
    if client:
        await client.send_output(line, line_type)
