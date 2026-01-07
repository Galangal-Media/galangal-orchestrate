"""
Workflow state management - Stage, TaskType, and WorkflowState.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class TaskType(str, Enum):
    """Type of task - determines which stages are required."""

    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    CHORE = "chore"
    DOCS = "docs"
    HOTFIX = "hotfix"

    @classmethod
    def from_str(cls, value: str) -> "TaskType":
        """Convert string to TaskType, defaulting to FEATURE."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.FEATURE

    def display_name(self) -> str:
        """Human-readable name for display."""
        return {
            TaskType.FEATURE: "Feature",
            TaskType.BUG_FIX: "Bug Fix",
            TaskType.REFACTOR: "Refactor",
            TaskType.CHORE: "Chore",
            TaskType.DOCS: "Docs",
            TaskType.HOTFIX: "Hotfix",
        }[self]

    def description(self) -> str:
        """Short description of this task type."""
        return {
            TaskType.FEATURE: "New functionality (full workflow)",
            TaskType.BUG_FIX: "Fix broken behavior (skip design)",
            TaskType.REFACTOR: "Restructure code (skip design, security)",
            TaskType.CHORE: "Dependencies, config, tooling",
            TaskType.DOCS: "Documentation only (minimal stages)",
            TaskType.HOTFIX: "Critical fix (expedited)",
        }[self]


class Stage(str, Enum):
    """Workflow stages."""

    PM = "PM"
    DESIGN = "DESIGN"
    PREFLIGHT = "PREFLIGHT"
    DEV = "DEV"
    MIGRATION = "MIGRATION"
    TEST = "TEST"
    CONTRACT = "CONTRACT"
    QA = "QA"
    BENCHMARK = "BENCHMARK"
    SECURITY = "SECURITY"
    REVIEW = "REVIEW"
    DOCS = "DOCS"
    COMPLETE = "COMPLETE"

    @classmethod
    def from_str(cls, value: str) -> "Stage":
        return cls(value.upper())

    def is_conditional(self) -> bool:
        """Return True if this stage only runs when conditions are met."""
        return self in (Stage.MIGRATION, Stage.CONTRACT, Stage.BENCHMARK)

    def is_skippable(self) -> bool:
        """Return True if this stage can be manually skipped."""
        return self in (
            Stage.DESIGN,
            Stage.MIGRATION,
            Stage.CONTRACT,
            Stage.BENCHMARK,
            Stage.SECURITY,
        )


# Stage order - the canonical sequence
STAGE_ORDER = [
    Stage.PM,
    Stage.DESIGN,
    Stage.PREFLIGHT,
    Stage.DEV,
    Stage.MIGRATION,
    Stage.TEST,
    Stage.CONTRACT,
    Stage.QA,
    Stage.BENCHMARK,
    Stage.SECURITY,
    Stage.REVIEW,
    Stage.DOCS,
    Stage.COMPLETE,
]


# Stages that are always skipped for each task type
TASK_TYPE_SKIP_STAGES: dict[TaskType, set[Stage]] = {
    TaskType.FEATURE: set(),  # Full workflow
    TaskType.BUG_FIX: {Stage.DESIGN, Stage.BENCHMARK},
    TaskType.REFACTOR: {
        Stage.DESIGN,
        Stage.MIGRATION,
        Stage.CONTRACT,
        Stage.BENCHMARK,
        Stage.SECURITY,
    },
    TaskType.CHORE: {Stage.DESIGN, Stage.MIGRATION, Stage.CONTRACT, Stage.BENCHMARK},
    TaskType.DOCS: {
        Stage.DESIGN,
        Stage.PREFLIGHT,
        Stage.MIGRATION,
        Stage.TEST,
        Stage.CONTRACT,
        Stage.QA,
        Stage.BENCHMARK,
        Stage.SECURITY,
    },
    TaskType.HOTFIX: {Stage.DESIGN, Stage.BENCHMARK},
}


def should_skip_for_task_type(stage: Stage, task_type: TaskType) -> bool:
    """Check if a stage should be skipped based on task type."""
    return stage in TASK_TYPE_SKIP_STAGES.get(task_type, set())


def get_hidden_stages_for_task_type(task_type: TaskType, config_skip: list[str] = None) -> set[str]:
    """Get stages to hide from progress bar based on task type and config.

    Args:
        task_type: The type of task being executed
        config_skip: List of stage names from config.stages.skip

    Returns:
        Set of stage name strings that should be hidden from the progress bar
    """
    hidden = set()

    # Add task type skips
    for stage in TASK_TYPE_SKIP_STAGES.get(task_type, set()):
        hidden.add(stage.value)

    # Add config skips
    if config_skip:
        for stage_name in config_skip:
            hidden.add(stage_name.upper())

    return hidden


@dataclass
class WorkflowState:
    """Persistent workflow state for a task."""

    stage: Stage
    attempt: int
    awaiting_approval: bool
    clarification_required: bool
    last_failure: str | None
    started_at: str
    task_description: str
    task_name: str
    task_type: TaskType = TaskType.FEATURE

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["task_type"] = self.task_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowState":
        return cls(
            stage=Stage.from_str(d["stage"]),
            attempt=d.get("attempt", 1),
            awaiting_approval=d.get("awaiting_approval", False),
            clarification_required=d.get("clarification_required", False),
            last_failure=d.get("last_failure"),
            started_at=d.get("started_at", datetime.now(timezone.utc).isoformat()),
            task_description=d.get("task_description", ""),
            task_name=d.get("task_name", ""),
            task_type=TaskType.from_str(d.get("task_type", "feature")),
        )

    @classmethod
    def new(
        cls, description: str, task_name: str, task_type: TaskType = TaskType.FEATURE
    ) -> "WorkflowState":
        return cls(
            stage=Stage.PM,
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            task_description=description,
            task_name=task_name,
            task_type=task_type,
        )


def get_task_dir(task_name: str) -> Path:
    """Get the directory for a task."""
    from galangal.config.loader import get_tasks_dir

    return get_tasks_dir() / task_name


def load_state(task_name: str | None = None) -> WorkflowState | None:
    """Load workflow state for a task."""
    from galangal.core.tasks import get_active_task

    if task_name is None:
        task_name = get_active_task()
    if task_name is None:
        return None

    state_file = get_task_dir(task_name) / "state.json"
    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            return WorkflowState.from_dict(json.load(f))
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error loading state: {e}")
        return None


def save_state(state: WorkflowState) -> None:
    """Save workflow state for a task."""
    task_dir = get_task_dir(state.task_name)
    task_dir.mkdir(parents=True, exist_ok=True)
    state_file = task_dir / "state.json"
    with open(state_file, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
