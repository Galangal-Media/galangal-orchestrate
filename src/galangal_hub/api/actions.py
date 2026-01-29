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


class QAAnswer(BaseModel):
    """A single question-answer pair."""

    question: str
    answer: str


class PromptResponse(BaseModel):
    """Request to respond to any prompt."""

    prompt_type: str  # The prompt type being responded to
    result: str  # The selected option result (e.g., "yes", "no", "quit")
    text_input: str | None = None  # Optional text input for prompts that need it
    answers: list[QAAnswer] | None = None  # Optional Q&A answers list


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
        task_name: Task to respond to (use "__prompt__" for prompts without a task).
        request: The response with prompt_type, result, and optional text_input.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")

    # Check task - allow "_" or "__prompt__" for prompts during task creation (no active task)
    if task_name not in ("_", "__prompt__"):
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

    # Use actual task name if available, otherwise empty string
    actual_task_name = agent.task.task_name if agent.task else ""

    # For Q&A answers, format them as text_input for the agent
    text_input = request.text_input
    if request.answers:
        # Format answers as numbered list for the agent to parse
        text_input = "\n".join(
            f"{i+1}. {a.answer}" for i, a in enumerate(request.answers)
        )

    action = HubAction(
        action_type=ActionType.RESPONSE,
        task_name=actual_task_name,
        data={
            "prompt_type": request.prompt_type,
            "result": request.result,
            "text_input": text_input,
        },
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send response to agent")

    # Clear the prompt on the hub side since we've responded
    await manager.clear_prompt(agent_id)

    return {
        "status": "responded",
        "task_name": actual_task_name,
        "prompt_type": request.prompt_type,
        "result": request.result,
    }


class CreateTaskRequest(BaseModel):
    """Request to create a new task."""

    task_name: str | None = None  # Manual task name
    task_description: str | None = None  # Manual description
    task_type: str = "feature"  # Task type (feature, bug_fix, etc.)
    github_issue: int | None = None  # GitHub issue number
    github_repo: str | None = None  # GitHub repo (owner/repo)


@router.post("/{agent_id}/create-task")
async def create_task(
    agent_id: str,
    request: CreateTaskRequest,
) -> dict:
    """
    Create a new task on an agent.

    Can create a task from:
    - Manual input (task_name + task_description)
    - GitHub issue (github_issue + github_repo)

    Args:
        agent_id: Target agent.
        request: Task creation parameters.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")

    # Validate request - need either manual input or GitHub issue
    if not request.task_name and not request.github_issue:
        raise HTTPException(
            status_code=400,
            detail="Must provide either task_name or github_issue"
        )

    # If GitHub issue provided, repo is required
    if request.github_issue and not request.github_repo:
        raise HTTPException(
            status_code=400,
            detail="github_repo is required when providing github_issue"
        )

    action = HubAction(
        action_type=ActionType.CREATE_TASK,
        task_name=request.task_name or f"issue-{request.github_issue}",
        data={
            "task_name": request.task_name,
            "task_description": request.task_description,
            "task_type": request.task_type,
            "github_issue": request.github_issue,
            "github_repo": request.github_repo,
        },
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send action to agent")

    return {
        "status": "creating",
        "task_name": request.task_name,
        "github_issue": request.github_issue,
    }


@router.get("/{agent_id}/github-issues")
async def get_github_issues(
    agent_id: str,
    refresh: bool = False,
    label: str = "galangal",
) -> dict:
    """
    Get GitHub issues from the connected agent.

    If issues are cached and refresh=False, returns cached issues.
    If refresh=True or no cached issues, requests fresh issues from agent.

    Args:
        agent_id: Target agent.
        refresh: Force refresh from GitHub.
        label: Label to filter issues by.
    """
    import asyncio

    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.connected:
        raise HTTPException(status_code=400, detail="Agent not connected")

    # Check if we have cached issues and don't need refresh
    cached = manager.get_github_issues(agent_id)
    if cached and not refresh:
        return {"issues": cached, "cached": True}

    # Request fresh issues from agent
    action = HubAction(
        action_type=ActionType.FETCH_GITHUB_ISSUES,
        task_name="",  # Not task-specific
        data={
            "request_id": f"issues-{agent_id}",
            "label": label,
        },
    )

    success = await manager.send_to_agent(agent_id, action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send request to agent")

    # Wait for response (poll for up to 10 seconds)
    for _ in range(20):
        await asyncio.sleep(0.5)
        issues = manager.get_github_issues(agent_id)
        if issues:
            return {"issues": issues, "cached": False}

    # Timeout - return empty or cached
    if cached:
        return {"issues": cached, "cached": True, "timeout": True}
    return {"issues": [], "cached": False, "timeout": True}


@router.get("/{agent_id}/output")
async def get_output_lines(
    agent_id: str,
    since: int = 0,
) -> dict:
    """
    Get recent output lines from an agent.

    Args:
        agent_id: Target agent.
        since: Return lines after this index (for incremental fetch).

    Returns:
        Dict with lines array and next_index for pagination.
    """
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    lines = manager.get_output_lines(agent_id, since)
    return {
        "lines": lines,
        "next_index": since + len(lines),
    }
