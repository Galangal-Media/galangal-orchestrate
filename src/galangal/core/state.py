"""
Workflow state management - Stage, TaskType, and WorkflowState.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
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


@dataclass(frozen=True)
class StageMetadata:
    """
    Rich metadata for a workflow stage.

    Provides centralized information about each stage including:
    - Display properties (name, description)
    - Behavioral flags (conditional, requires approval, skippable)
    - Artifact dependencies (produces, requires)

    This metadata is used by the TUI, validation, and workflow logic.
    """

    display_name: str
    description: str
    is_conditional: bool = False
    requires_approval: bool = False
    is_skippable: bool = False
    produces_artifacts: tuple[str, ...] = ()
    requires_artifacts: tuple[str, ...] = ()
    skip_artifact: str | None = None  # e.g., "MIGRATION_SKIP.md"


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

    @property
    def metadata(self) -> StageMetadata:
        """Get rich metadata for this stage."""
        return STAGE_METADATA[self]

    def is_conditional(self) -> bool:
        """Return True if this stage only runs when conditions are met."""
        return self.metadata.is_conditional

    def is_skippable(self) -> bool:
        """Return True if this stage can be manually skipped."""
        return self.metadata.is_skippable


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


# Rich metadata for each stage
STAGE_METADATA: dict[Stage, StageMetadata] = {
    Stage.PM: StageMetadata(
        display_name="PM",
        description="Define requirements and generate spec",
        requires_approval=True,
        produces_artifacts=("SPEC.md", "PLAN.md"),
    ),
    Stage.DESIGN: StageMetadata(
        display_name="Design",
        description="Create implementation plan and architecture",
        requires_approval=True,
        is_skippable=True,
        requires_artifacts=("SPEC.md",),
        produces_artifacts=("DESIGN.md",),
        skip_artifact="DESIGN_SKIP.md",
    ),
    Stage.PREFLIGHT: StageMetadata(
        display_name="Preflight",
        description="Verify environment and dependencies",
        produces_artifacts=("PREFLIGHT_REPORT.md",),
    ),
    Stage.DEV: StageMetadata(
        display_name="Development",
        description="Implement the feature or fix",
        requires_artifacts=("SPEC.md", "PLAN.md"),
        produces_artifacts=("DEVELOPMENT.md",),
    ),
    Stage.MIGRATION: StageMetadata(
        display_name="Migration",
        description="Database and data migrations",
        is_conditional=True,
        is_skippable=True,
        produces_artifacts=("MIGRATION_REPORT.md",),
        skip_artifact="MIGRATION_SKIP.md",
    ),
    Stage.TEST: StageMetadata(
        display_name="Test",
        description="Write and run tests",
        produces_artifacts=("TEST_PLAN.md",),
    ),
    Stage.CONTRACT: StageMetadata(
        display_name="Contract",
        description="API contract testing",
        is_conditional=True,
        is_skippable=True,
        produces_artifacts=("CONTRACT_REPORT.md",),
        skip_artifact="CONTRACT_SKIP.md",
    ),
    Stage.QA: StageMetadata(
        display_name="QA",
        description="Quality assurance review",
        produces_artifacts=("QA_REPORT.md",),
    ),
    Stage.BENCHMARK: StageMetadata(
        display_name="Benchmark",
        description="Performance benchmarking",
        is_conditional=True,
        is_skippable=True,
        produces_artifacts=("BENCHMARK_REPORT.md",),
        skip_artifact="BENCHMARK_SKIP.md",
    ),
    Stage.SECURITY: StageMetadata(
        display_name="Security",
        description="Security review and audit",
        is_skippable=True,
        produces_artifacts=("SECURITY_CHECKLIST.md",),
    ),
    Stage.REVIEW: StageMetadata(
        display_name="Review",
        description="Code review and final checks",
        produces_artifacts=("REVIEW_NOTES.md",),
    ),
    Stage.DOCS: StageMetadata(
        display_name="Docs",
        description="Update documentation",
        produces_artifacts=("DOCS_REPORT.md",),
    ),
    Stage.COMPLETE: StageMetadata(
        display_name="Complete",
        description="Workflow completed",
    ),
}


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


def get_conditional_stages() -> dict[Stage, str]:
    """
    Get mapping of conditional stages to their skip artifact names.

    Returns:
        Dict mapping Stage -> skip artifact filename (e.g., "MIGRATION_SKIP.md")
    """
    return {
        stage: metadata.skip_artifact
        for stage, metadata in STAGE_METADATA.items()
        if metadata.is_conditional and metadata.skip_artifact
    }


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


# Maximum rollbacks to the same stage within the time window
MAX_ROLLBACKS_PER_STAGE = 3
ROLLBACK_TIME_WINDOW_HOURS = 1


@dataclass
class RollbackEvent:
    """
    Record of a rollback event in the workflow.

    Tracks when a stage failed validation and triggered a rollback
    to an earlier stage. Used to detect rollback loops and prevent
    infinite retry cycles.

    Attributes:
        timestamp: When the rollback occurred (ISO format string).
        from_stage: Stage that failed and triggered the rollback.
        to_stage: Target stage to roll back to.
        reason: Description of why the rollback was needed.
    """

    timestamp: str
    from_stage: str
    to_stage: str
    reason: str

    @classmethod
    def create(cls, from_stage: "Stage", to_stage: "Stage", reason: str) -> "RollbackEvent":
        """Create a new rollback event with current timestamp."""
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            from_stage=from_stage.value,
            to_stage=to_stage.value,
            reason=reason,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RollbackEvent":
        """Create from dictionary."""
        return cls(
            timestamp=d["timestamp"],
            from_stage=d["from_stage"],
            to_stage=d["to_stage"],
            reason=d["reason"],
        )


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
    rollback_history: list[RollbackEvent] = field(default_factory=list)

    # -------------------------------------------------------------------------
    # Retry management methods
    # -------------------------------------------------------------------------

    def record_failure(self, error: str) -> None:
        """
        Record a failed attempt.

        Increments the attempt counter and stores the error message
        for context in the next retry.

        Args:
            error: Error message from the failed attempt.
        """
        self.attempt += 1
        self.last_failure = error

    def can_retry(self, max_retries: int) -> bool:
        """
        Check if another retry attempt is allowed.

        Args:
            max_retries: Maximum number of attempts allowed.

        Returns:
            True if attempt <= max_retries, False if exhausted.
        """
        return self.attempt <= max_retries

    def reset_attempts(self, clear_failure: bool = True) -> None:
        """
        Reset attempt counter for a new stage or after user intervention.

        Called when:
        - Advancing to a new stage (clear_failure=True)
        - User chooses to retry after max attempts (clear_failure=True)
        - Rolling back to an earlier stage (clear_failure=False to preserve context)

        Args:
            clear_failure: If True, also clears last_failure. Set to False
                when rolling back to preserve feedback context for the next attempt.
        """
        self.attempt = 1
        if clear_failure:
            self.last_failure = None

    # -------------------------------------------------------------------------
    # Rollback management methods
    # -------------------------------------------------------------------------

    def record_rollback(self, from_stage: Stage, to_stage: Stage, reason: str) -> None:
        """
        Record a rollback event in the history.

        Called when validation fails and triggers a rollback to an earlier stage.
        The history is used to detect rollback loops and prevent infinite retries.

        Args:
            from_stage: Stage that failed and triggered the rollback.
            to_stage: Target stage to roll back to.
            reason: Description of why the rollback was needed.
        """
        event = RollbackEvent.create(from_stage, to_stage, reason)
        self.rollback_history.append(event)

    def should_allow_rollback(self, target_stage: Stage) -> bool:
        """
        Check if a rollback to the target stage is allowed.

        Prevents infinite rollback loops by limiting the number of rollbacks
        to the same stage within a time window.

        Args:
            target_stage: Stage to potentially roll back to.

        Returns:
            True if rollback is allowed, False if too many recent rollbacks.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ROLLBACK_TIME_WINDOW_HOURS)
        cutoff_str = cutoff.isoformat()

        recent_rollbacks = [
            r for r in self.rollback_history
            if r.to_stage == target_stage.value and r.timestamp > cutoff_str
        ]

        return len(recent_rollbacks) < MAX_ROLLBACKS_PER_STAGE

    def get_rollback_count(self, target_stage: Stage) -> int:
        """
        Get the number of recent rollbacks to a stage.

        Args:
            target_stage: Stage to count rollbacks for.

        Returns:
            Number of rollbacks to this stage in the time window.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ROLLBACK_TIME_WINDOW_HOURS)
        cutoff_str = cutoff.isoformat()

        return len([
            r for r in self.rollback_history
            if r.to_stage == target_stage.value and r.timestamp > cutoff_str
        ])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["task_type"] = self.task_type.value
        # rollback_history is already converted to list of dicts by asdict
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowState":
        # Parse rollback history if present
        rollback_history = [
            RollbackEvent.from_dict(r) for r in d.get("rollback_history", [])
        ]

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
            rollback_history=rollback_history,
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
