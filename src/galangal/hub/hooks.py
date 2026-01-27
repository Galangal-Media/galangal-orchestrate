"""
Hooks for hub integration.

These hooks are called at key points in the workflow to sync state
and events with the hub server.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galangal.core.state import Stage, WorkflowState

from galangal.hub.client import EventType, get_hub_client


def notify_state_saved(state: WorkflowState) -> None:
    """
    Notify hub that state was saved.

    Called after save_state() completes successfully.

    Args:
        state: The workflow state that was saved.
    """
    client = get_hub_client()
    if client and client.connected:
        # Run async in background
        asyncio.create_task(_send_state_update(state))


async def _send_state_update(state: WorkflowState) -> None:
    """Send state update to hub."""
    client = get_hub_client()
    if client:
        await client.send_state(state)


def notify_stage_start(state: WorkflowState, stage: Stage) -> None:
    """
    Notify hub that a stage is starting.

    Args:
        state: Current workflow state.
        stage: The stage that is starting.
    """
    client = get_hub_client()
    if client and client.connected:
        asyncio.create_task(
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
        asyncio.create_task(
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
        asyncio.create_task(
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
        asyncio.create_task(
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
        asyncio.create_task(
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
        asyncio.create_task(
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
