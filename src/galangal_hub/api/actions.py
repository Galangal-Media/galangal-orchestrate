"""
Remote action API endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from galangal_hub.connection import manager
from galangal_hub.models import ActionType, HubAction

router = APIRouter(prefix="/api/actions", tags=["actions"])


class ApprovalRequest(BaseModel):
    """Request to approve a stage."""

    feedback: str | None = None


class RejectRequest(BaseModel):
    """Request to reject a stage."""

    reason: str


class SkipRequest(BaseModel):
    """Request to skip a stage."""

    reason: str | None = None


class RollbackRequest(BaseModel):
    """Request to rollback to a stage."""

    target_stage: str
    feedback: str | None = None


class PromptResponse(BaseModel):
    """Request to respond to any prompt."""

    prompt_type: str  # The prompt type being responded to
    result: str  # The selected option result (e.g., "yes", "no", "quit")
    text_input: str | None = None  # Optional text input for prompts that need it


@router.post("/{agent_id}/{task_name}/approve")
async def approve_task(
    agent_id: str,
    task_name: str,
    request: ApprovalRequest | None = None,
) -> dict:
    """
    Approve the current stage for a task.

    Args:
        agent_id: Target agent.
        task_name: Task to approve.
        request: Optional approval feedback.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")
    if not agent.task or agent.task.task_name != task_name:
        raise HTTPException(status_code=404, detail="Task not found")
    if not agent.task.awaiting_approval:
        raise HTTPException(status_code=400, detail="Task not awaiting approval")

    action = HubAction(
        action_type=ActionType.APPROVE,
        task_name=task_name,
        data={"feedback": request.feedback if request else None},
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send action to agent")

    return {"status": "approved", "task_name": task_name}


@router.post("/{agent_id}/{task_name}/reject")
async def reject_task(
    agent_id: str,
    task_name: str,
    request: RejectRequest,
) -> dict:
    """
    Reject the current stage for a task.

    Args:
        agent_id: Target agent.
        task_name: Task to reject.
        request: Rejection reason.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")
    if not agent.task or agent.task.task_name != task_name:
        raise HTTPException(status_code=404, detail="Task not found")
    if not agent.task.awaiting_approval:
        raise HTTPException(status_code=400, detail="Task not awaiting approval")

    action = HubAction(
        action_type=ActionType.REJECT,
        task_name=task_name,
        data={"reason": request.reason},
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send action to agent")

    return {"status": "rejected", "task_name": task_name, "reason": request.reason}


@router.post("/{agent_id}/{task_name}/skip")
async def skip_task_stage(
    agent_id: str,
    task_name: str,
    request: SkipRequest | None = None,
) -> dict:
    """
    Skip the current stage for a task.

    Args:
        agent_id: Target agent.
        task_name: Task to skip stage for.
        request: Optional skip reason.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")
    if not agent.task or agent.task.task_name != task_name:
        raise HTTPException(status_code=404, detail="Task not found")

    action = HubAction(
        action_type=ActionType.SKIP,
        task_name=task_name,
        data={"reason": request.reason if request else None},
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send action to agent")

    return {"status": "skipping", "task_name": task_name}


@router.post("/{agent_id}/{task_name}/rollback")
async def rollback_task(
    agent_id: str,
    task_name: str,
    request: RollbackRequest,
) -> dict:
    """
    Rollback a task to a previous stage.

    Args:
        agent_id: Target agent.
        task_name: Task to rollback.
        request: Rollback target and feedback.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")
    if not agent.task or agent.task.task_name != task_name:
        raise HTTPException(status_code=404, detail="Task not found")

    action = HubAction(
        action_type=ActionType.ROLLBACK,
        task_name=task_name,
        data={
            "target_stage": request.target_stage,
            "feedback": request.feedback,
        },
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send action to agent")

    return {
        "status": "rolling_back",
        "task_name": task_name,
        "target_stage": request.target_stage,
    }


@router.post("/{agent_id}/{task_name}/interrupt")
async def interrupt_task(
    agent_id: str,
    task_name: str,
) -> dict:
    """
    Interrupt a running task.

    Args:
        agent_id: Target agent.
        task_name: Task to interrupt.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")
    if not agent.task or agent.task.task_name != task_name:
        raise HTTPException(status_code=404, detail="Task not found")

    action = HubAction(
        action_type=ActionType.INTERRUPT,
        task_name=task_name,
        data={},
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send action to agent")

    return {"status": "interrupting", "task_name": task_name}


@router.post("/{agent_id}/{task_name}/respond")
async def respond_to_prompt(
    agent_id: str,
    task_name: str,
    request: PromptResponse,
) -> dict:
    """
    Respond to any prompt being displayed by an agent.

    This is a general-purpose endpoint that can respond to any prompt type,
    not just approval gates. Use this when the agent has an active prompt.

    Args:
        agent_id: Target agent.
        task_name: Task to respond to.
        request: The response with prompt_type, result, and optional text_input.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")
    if not agent.task or agent.task.task_name != task_name:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check if there's an active prompt
    if not agent.current_prompt:
        raise HTTPException(status_code=400, detail="No active prompt")

    # Optionally validate that the prompt_type matches
    if agent.current_prompt.prompt_type != request.prompt_type:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt type mismatch: expected {agent.current_prompt.prompt_type}, got {request.prompt_type}"
        )

    action = HubAction(
        action_type=ActionType.RESPONSE,
        task_name=task_name,
        data={
            "prompt_type": request.prompt_type,
            "result": request.result,
            "text_input": request.text_input,
        },
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send response to agent")

    # Clear the prompt on the hub side since we've responded
    await manager.clear_prompt(agent_id)

    return {
        "status": "responded",
        "task_name": task_name,
        "prompt_type": request.prompt_type,
        "result": request.result,
    }
