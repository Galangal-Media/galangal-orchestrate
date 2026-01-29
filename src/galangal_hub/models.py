"""
Protocol models for hub communication.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Types of messages in the hub protocol."""

    # Agent -> Hub
    REGISTER = "register"
    STATE_UPDATE = "state_update"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    PROMPT = "prompt"  # Send current prompt with options
    ARTIFACTS = "artifacts"  # Send artifact contents
    GITHUB_ISSUES = "github_issues"  # Response with GitHub issues list
    OUTPUT = "output"  # Streaming CLI output lines

    # Hub -> Agent
    ACTION = "action"
    ACTION_RESULT = "action_result"


class EventType(str, Enum):
    """Types of workflow events."""

    STAGE_START = "stage_start"
    STAGE_COMPLETE = "stage_complete"
    STAGE_FAIL = "stage_fail"
    APPROVAL_NEEDED = "approval_needed"
    ROLLBACK = "rollback"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"


class ActionType(str, Enum):
    """Types of actions that can be sent to agents."""

    APPROVE = "approve"
    REJECT = "reject"
    SKIP = "skip"
    ROLLBACK = "rollback"
    INTERRUPT = "interrupt"
    RESPONSE = "response"  # Response to any prompt (not just approval)
    CREATE_TASK = "create_task"  # Create a new task
    FETCH_GITHUB_ISSUES = "fetch_github_issues"  # Request GitHub issues list


class AgentInfo(BaseModel):
    """Information about a connected agent."""

    agent_id: str
    hostname: str
    project_name: str
    project_path: str
    agent_name: str
    connected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskState(BaseModel):
    """Current state of a task from an agent."""

    task_name: str
    task_description: str
    task_type: str
    stage: str
    attempt: int = 1
    awaiting_approval: bool = False
    last_failure: str | None = None
    started_at: str
    stage_durations: dict[str, int] | None = None
    github_issue: int | None = None
    github_repo: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowEvent(BaseModel):
    """A workflow event from an agent."""

    event_type: EventType
    timestamp: datetime
    agent_id: str
    task_name: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    """Message from an agent to the hub."""

    type: MessageType
    agent_id: str
    timestamp: datetime
    payload: dict[str, Any]


class HubAction(BaseModel):
    """Action to send from hub to agent."""

    action_type: ActionType
    task_name: str
    data: dict[str, Any] = Field(default_factory=dict)


class PromptOption(BaseModel):
    """An option for a prompt."""

    key: str  # Keyboard shortcut (e.g., "1", "2")
    label: str  # Display label (e.g., "Approve", "Reject")
    result: str  # Result value to return (e.g., "yes", "no")
    color: str | None = None  # Optional color for styling


class PromptData(BaseModel):
    """Data about a prompt being displayed to the user."""

    prompt_type: str  # PromptType enum value
    message: str  # Display message
    options: list[PromptOption]  # Available choices
    questions: list[str] = Field(default_factory=list)  # Questions for Q&A prompts
    artifacts: list[str] = Field(default_factory=list)  # Relevant artifact names
    context: dict[str, Any] = Field(default_factory=dict)  # Optional context
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentWithState(BaseModel):
    """Agent info combined with current task state."""

    agent: AgentInfo
    task: TaskState | None = None
    connected: bool = True
    current_prompt: PromptData | None = None  # Currently displayed prompt
    artifacts: dict[str, str] = Field(default_factory=dict)  # Artifact name -> content


class GitHubIssueInfo(BaseModel):
    """GitHub issue information for display in Hub UI."""

    number: int
    title: str
    labels: list[str] = Field(default_factory=list)
    state: str = "open"
    author: str = ""
