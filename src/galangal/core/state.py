"""
Workflow state management - Stage, TaskType, and WorkflowState.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any


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
        """Convert string to TaskType, defaulting to FEATURE.

        Handles multiple string formats:
        - Enum values: "feature", "bug_fix", "refactor", etc.
        - UI keys: "bugfix" (maps to BUG_FIX)
        - GitHub hints: "bug_fix" from label inference
        """
        normalized = value.lower().strip()

        # Handle aliases that don't match enum values directly
        aliases = {
            "bugfix": cls.BUG_FIX,
            "bug": cls.BUG_FIX,
            "fix": cls.BUG_FIX,
            "enhancement": cls.FEATURE,
            "feat": cls.FEATURE,
        }

        if normalized in aliases:
            return aliases[normalized]

        try:
            return cls(normalized)
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

    def short_description(self) -> str:
        """Brief description of what this task type is for."""
        return {
            TaskType.FEATURE: "New functionality",
            TaskType.BUG_FIX: "Fix broken behavior",
            TaskType.REFACTOR: "Restructure code",
            TaskType.CHORE: "Dependencies, config, tooling",
            TaskType.DOCS: "Documentation only",
            TaskType.HOTFIX: "Critical fix",
        }[self]

    def description(self) -> str:
        """Full description with pipeline (derived from TASK_TYPE_SKIP_STAGES)."""
        pipeline = get_task_type_pipeline(self)
        if self == TaskType.FEATURE:
            return f"{self.short_description()} (full workflow)"
        return f"{self.short_description()} ({pipeline})"


@dataclass(frozen=True)
class StageMetadata:
    """
    Rich metadata for a workflow stage.

    Provides centralized information about each stage including:
    - Display properties (name, description)
    - Behavioral flags (conditional, requires approval, skippable)
    - Artifact dependencies (produces, requires)
    - Decision file configuration for validation
    - Context artifacts for prompt building

    This metadata is used by the TUI, validation, prompt builder, and workflow logic.
    """

    display_name: str
    description: str
    is_conditional: bool = False
    requires_approval: bool = False
    is_skippable: bool = False
    produces_artifacts: tuple[str, ...] = ()
    skip_artifact: str | None = None  # e.g., "MIGRATION_SKIP.md"
    approval_artifact: str | None = (
        None  # e.g., "APPROVAL.md" - checked when requires_approval=True
    )
    # Decision file for validation (e.g., "SECURITY_DECISION")
    decision_file: str | None = None
    # Valid decision values and their outcomes: (value, success, message, rollback_to, is_fast_track)
    decision_outcomes: tuple[tuple[str, bool, str, str | None, bool], ...] = ()
    # Schema for read-only backend structured output parsing
    # {
    #   "notes_file": "ARTIFACT.md",
    #   "notes_field": "json_field_name",
    #   "decision_file": "DECISION_FILE",
    #   "decision_field": "decision",
    #   "issues_field": "issues"
    # }
    artifact_schema: dict[str, str | None] | None = None
    # If True, this stage remains in passed_stages during rollback
    # (e.g., TEST stage - tests don't need to be rewritten after rollback)
    preserve_on_rollback: bool = False


class Stage(str, Enum):
    """Workflow stages."""

    PM = "PM"
    DESIGN = "DESIGN"
    PREFLIGHT = "PREFLIGHT"
    DEV = "DEV"
    MIGRATION = "MIGRATION"
    TEST = "TEST"
    TEST_GATE = "TEST_GATE"
    CONTRACT = "CONTRACT"
    QA = "QA"
    BENCHMARK = "BENCHMARK"
    SECURITY = "SECURITY"
    REVIEW = "REVIEW"
    DOCS = "DOCS"
    SUMMARY = "SUMMARY"
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
    Stage.TEST_GATE,
    Stage.CONTRACT,
    Stage.QA,
    Stage.BENCHMARK,
    Stage.SECURITY,
    Stage.REVIEW,
    Stage.DOCS,
    Stage.SUMMARY,
    Stage.COMPLETE,
]


# Rich metadata for each stage
STAGE_METADATA: dict[Stage, StageMetadata] = {
    Stage.PM: StageMetadata(
        display_name="PM",
        description="Define requirements and generate spec",
        requires_approval=True,
        approval_artifact="APPROVAL.md",
        produces_artifacts=("SPEC.md", "PLAN.md", "DISCOVERY_LOG.md"),
    ),
    Stage.DESIGN: StageMetadata(
        display_name="Design",
        description="Create implementation plan and architecture",
        is_skippable=True,
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
        description="Write tests (does not run them)",
        produces_artifacts=("TEST_PLAN.md",),
        preserve_on_rollback=True,  # Tests don't need to be rewritten after rollback
    ),
    Stage.TEST_GATE: StageMetadata(
        display_name="Test Gate",
        description="Verify configured test suites pass",
        is_conditional=True,
        is_skippable=True,
        produces_artifacts=("TEST_GATE_RESULTS.md",),
        skip_artifact="TEST_GATE_SKIP.md",
        decision_file="TEST_GATE_DECISION",
        decision_outcomes=(
            ("PASS", True, "All configured tests passed", None, False),
            (
                "FAIL",
                False,
                "Test gate failed - tests did not pass",
                "DEV",
                False,
            ),
        ),
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
        decision_file="QA_DECISION",
        decision_outcomes=(
            ("PASS", True, "QA passed", None, False),
            ("FAIL", False, "QA failed", "DEV", False),
        ),
        artifact_schema={
            "notes_file": "QA_REPORT.md",
            "notes_field": "qa_report",
            "decision_file": "QA_DECISION",
            "decision_field": "decision",
            "issues_field": "issues",
        },
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
        skip_artifact="SECURITY_SKIP.md",
        decision_file="SECURITY_DECISION",
        decision_outcomes=(
            ("APPROVED", True, "Security review approved", None, False),
            ("REJECTED", False, "Security review found blocking issues", "DEV", False),
            ("BLOCKED", False, "Security review found blocking issues", "DEV", False),
        ),
        artifact_schema={
            "notes_file": "SECURITY_CHECKLIST.md",
            "notes_field": "security_checklist",
            "decision_file": "SECURITY_DECISION",
            "decision_field": "decision",
            "issues_field": "issues",
        },
    ),
    Stage.REVIEW: StageMetadata(
        display_name="Review",
        description="Code review and final checks",
        produces_artifacts=("REVIEW_NOTES.md",),
        decision_file="REVIEW_DECISION",
        decision_outcomes=(
            ("APPROVE", True, "Review approved", None, False),
            ("REQUEST_CHANGES", False, "Review requested changes", "DEV", False),
            (
                "REQUEST_MINOR_CHANGES",
                False,
                "Review requested minor changes (fast-track)",
                "DEV",
                True,
            ),
        ),
        artifact_schema={
            "notes_file": "REVIEW_NOTES.md",
            "notes_field": "review_notes",
            "decision_file": "REVIEW_DECISION",
            "decision_field": "decision",
            "issues_field": "issues",
        },
    ),
    Stage.DOCS: StageMetadata(
        display_name="Docs",
        description="Update documentation",
        produces_artifacts=("DOCS_REPORT.md",),
    ),
    Stage.SUMMARY: StageMetadata(
        display_name="Summary",
        description="Generate workflow summary for PR",
        is_skippable=True,
        produces_artifacts=("SUMMARY.md",),
        skip_artifact="SUMMARY_SKIP.md",
    ),
    Stage.COMPLETE: StageMetadata(
        display_name="Complete",
        description="Workflow completed",
    ),
}


# Stages that are always skipped for each task type
TASK_TYPE_SKIP_STAGES: dict[TaskType, set[Stage]] = {
    # FEATURE: Full workflow - PM → DESIGN → PREFLIGHT → DEV → all validation stages
    TaskType.FEATURE: set(),
    # BUG_FIX: PM → DEV → TEST → QA → REVIEW (skip design, run QA for regression check)
    TaskType.BUG_FIX: {
        Stage.DESIGN,
        Stage.MIGRATION,
        Stage.CONTRACT,
        Stage.BENCHMARK,
        Stage.SECURITY,
        Stage.DOCS,
    },
    # REFACTOR: PM → DESIGN → DEV → TEST → REVIEW (code restructuring, needs design and review)
    TaskType.REFACTOR: {
        Stage.MIGRATION,
        Stage.CONTRACT,
        Stage.QA,
        Stage.BENCHMARK,
        Stage.SECURITY,
        Stage.DOCS,
    },
    # CHORE: PM → DEV → TEST → REVIEW (dependencies, config, tooling)
    TaskType.CHORE: {
        Stage.DESIGN,
        Stage.MIGRATION,
        Stage.CONTRACT,
        Stage.QA,
        Stage.BENCHMARK,
        Stage.SECURITY,
        Stage.DOCS,
    },
    # DOCS: PM → DOCS (documentation only - skip everything else)
    TaskType.DOCS: {
        Stage.DESIGN,
        Stage.PREFLIGHT,
        Stage.DEV,
        Stage.MIGRATION,
        Stage.TEST,
        Stage.TEST_GATE,
        Stage.CONTRACT,
        Stage.QA,
        Stage.BENCHMARK,
        Stage.SECURITY,
        Stage.REVIEW,
    },
    # HOTFIX: PM → DEV → TEST (critical fix - expedited, minimal stages)
    TaskType.HOTFIX: {
        Stage.DESIGN,
        Stage.PREFLIGHT,
        Stage.MIGRATION,
        Stage.CONTRACT,
        Stage.QA,
        Stage.BENCHMARK,
        Stage.SECURITY,
        Stage.REVIEW,
        Stage.DOCS,
    },
}


def should_skip_for_task_type(stage: Stage, task_type: TaskType) -> bool:
    """Check if a stage should be skipped based on task type."""
    return stage in TASK_TYPE_SKIP_STAGES.get(task_type, set())


def get_task_type_pipeline(task_type: TaskType) -> str:
    """
    Get the stage pipeline string for a task type.

    Derives the pipeline from TASK_TYPE_SKIP_STAGES, ensuring it stays
    in sync with the actual skip configuration.

    Args:
        task_type: The task type to get the pipeline for.

    Returns:
        Pipeline string like "PM → DEV → TEST → QA"
    """
    skip_stages = TASK_TYPE_SKIP_STAGES.get(task_type, set())
    stages = [s.value for s in STAGE_ORDER if s not in skip_stages and s != Stage.COMPLETE]
    return " → ".join(stages)


def get_workflow_diagram() -> str:
    """
    Get the full workflow pipeline diagram.

    Returns:
        Multi-line string showing the stage pipeline with conditional markers.
    """
    # Split into two lines for readability
    first_half = STAGE_ORDER[:6]  # PM through MIGRATION
    second_half = STAGE_ORDER[6:-1]  # TEST through DOCS (exclude COMPLETE)

    # Mark conditional stages with *
    def format_stage(s: Stage) -> str:
        meta = STAGE_METADATA.get(s)
        marker = "*" if meta and meta.is_conditional else ""
        return f"{s.value}{marker}"

    line1 = " → ".join(format_stage(s) for s in first_half)
    line2 = " → ".join(format_stage(s) for s in second_half) + " → COMPLETE"

    return f"{line1} →\n  {line2}"


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


def get_all_artifact_names() -> list[str]:
    """
    Get all artifact names for status display.

    Derives the complete list from STAGE_METADATA to ensure it stays in sync.
    Includes: produces, skip, approval, and decision artifacts.

    Returns:
        Sorted list of all artifact names.
    """
    artifacts: set[str] = set()

    for metadata in STAGE_METADATA.values():
        # Add produced artifacts
        artifacts.update(metadata.produces_artifacts)

        # Add skip artifact if defined
        if metadata.skip_artifact:
            artifacts.add(metadata.skip_artifact)

        # Add approval artifact if defined
        if metadata.approval_artifact:
            artifacts.add(metadata.approval_artifact)

        # Add decision file if defined (no .md extension)
        if metadata.decision_file:
            artifacts.add(metadata.decision_file)

    # Add system-generated artifacts not tied to specific stages
    artifacts.add("ROLLBACK.md")
    artifacts.add("TEST_SUMMARY.md")
    artifacts.add("VALIDATION_REPORT.md")
    artifacts.add("STAGE_PLAN.md")

    return sorted(artifacts)


def get_decision_config(stage: Stage) -> dict[str, tuple[bool, str, str | None, bool]] | None:
    """
    Get decision file configuration for a stage.

    Returns a dict mapping decision values to their outcomes:
    {value: (success, message, rollback_to, is_fast_track)}

    Args:
        stage: The stage to get decision config for.

    Returns:
        Decision config dict or None if stage has no decision file.
    """
    metadata = stage.metadata
    if not metadata.decision_file or not metadata.decision_outcomes:
        return None

    return {
        value: (success, message, rollback_to, is_fast_track)
        for value, success, message, rollback_to, is_fast_track in metadata.decision_outcomes
    }


def get_decision_file_name(stage: Stage) -> str | None:
    """
    Get the decision file name for a stage.

    Args:
        stage: The stage to get the decision file name for.

    Returns:
        Decision file name (e.g., "QA_DECISION") or None if stage has no decision file.
    """
    metadata = stage.metadata
    return metadata.decision_file if metadata else None


def get_decision_values(stage: Stage) -> list[str]:
    """
    Get the valid decision values for a stage.

    Args:
        stage: The stage to get decision values for.

    Returns:
        List of valid decision values (e.g., ["PASS", "FAIL"]), empty if no decision file.
    """
    metadata = stage.metadata
    if not metadata or not metadata.decision_outcomes:
        return []
    return [value for value, *_ in metadata.decision_outcomes]


def get_decision_words(stage: Stage) -> tuple[str | None, str | None]:
    """
    Get the approve and reject decision words for a stage.

    Derives the words from STAGE_METADATA.decision_outcomes:
    - approve_word: First outcome where success=True
    - reject_word: First outcome where success=False

    Args:
        stage: The stage to get decision words for.

    Returns:
        (approve_word, reject_word) tuple, or (None, None) if stage has no decision file.
    """
    metadata = stage.metadata
    if not metadata or not metadata.decision_outcomes:
        return (None, None)

    approve_word = next(
        (value for value, success, *_ in metadata.decision_outcomes if success), None
    )
    reject_word = next(
        (value for value, success, *_ in metadata.decision_outcomes if not success), None
    )
    return (approve_word, reject_word)


def get_decision_info_for_prompt(stage: Stage) -> str | None:
    """
    Get formatted decision file info for prompt injection.

    Returns a markdown snippet describing the decision file and valid values,
    suitable for injection into stage prompts.

    Args:
        stage: The stage to get decision info for.

    Returns:
        Markdown-formatted decision file instructions, or None if no decision file.
    """
    metadata = stage.metadata
    if not metadata or not metadata.decision_file or not metadata.decision_outcomes:
        return None

    decision_file = metadata.decision_file
    values = [value for value, *_ in metadata.decision_outcomes]

    # Build the prompt snippet
    lines = [
        "## CRITICAL: Decision File",
        "",
        "After completing this stage, you MUST create a decision file:",
        "",
        f"**File:** `{decision_file}` (no extension)",
        f"**Contents:** Exactly one of: `{'`, `'.join(values)}`",
        "",
        "Example:",
        "```",
        values[0],  # Show first value as example
        "```",
        "",
        "This file must contain ONLY the decision word, nothing else.",
        "The validation system reads this file to determine the stage result.",
    ]

    return "\n".join(lines)


def parse_stage_arg(
    stage_arg: str,
    exclude_complete: bool = False,
) -> Stage | None:
    """Parse a stage argument string and return the Stage enum.

    Handles invalid stage errors with consistent messaging.

    Args:
        stage_arg: The stage argument from CLI (e.g., "pm", "DEV")
        exclude_complete: If True, COMPLETE is not allowed and excluded from valid list

    Returns:
        Stage enum if valid, None if invalid (error already printed)
    """
    from galangal.ui.console import console, print_error

    stage_str = stage_arg.upper()
    try:
        stage = Stage.from_str(stage_str)
    except ValueError:
        print_error(f"Invalid stage: '{stage_arg}'")
        valid = [s.value.lower() for s in Stage if not (exclude_complete and s == Stage.COMPLETE)]
        console.print(f"[dim]Valid stages: {', '.join(valid)}[/dim]")
        return None

    if exclude_complete and stage == Stage.COMPLETE:
        print_error("COMPLETE stage is not allowed here.")
        return None

    return stage


def get_hidden_stages_for_task_type(
    task_type: TaskType, config_skip: list[str] | None = None
) -> set[str]:
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

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "RollbackEvent":
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

    # PM Discovery Q&A tracking
    qa_rounds: list[dict[str, Any]] | None = None  # [{"questions": [...], "answers": [...]}]
    qa_complete: bool = False

    # PM-driven stage planning
    # Maps stage name to {"action": "skip"|"run", "reason": "..."}
    stage_plan: dict[str, dict[str, Any]] | None = None

    # Stage timing tracking
    stage_start_time: str | None = None  # ISO timestamp when current stage started
    stage_durations: dict[str, int] | None = None  # Completed stage durations in seconds

    # GitHub integration
    github_issue: int | None = None  # Issue number if created from GitHub
    github_repo: str | None = None  # owner/repo for PR creation
    screenshots: list[str] | None = None  # Local paths to screenshots from issue

    # Fast-track rollback support
    # Stages that passed since last DEV run (cleared when entering DEV)
    passed_stages: set[str] = field(default_factory=set)
    # Stages to skip on this iteration (set from passed_stages on minor rollback)
    fast_track_skip: set[str] = field(default_factory=set)

    # Per-stage commit tracking
    base_commit_sha: str | None = None  # Commit SHA at task start (squash target)
    stage_commits: list[dict[str, str]] | None = None  # [{"stage": "DEV", "sha": "abc123"}]

    # Artifact lineage tracking for staleness detection
    # Maps artifact name to ArtifactLineage with section hashes
    artifact_lineage: dict[str, Any] = field(default_factory=dict)
    # Maps stage name to StageLineage with input hashes
    stage_lineage: dict[str, Any] = field(default_factory=dict)

    # -------------------------------------------------------------------------
    # Retry management methods
    # -------------------------------------------------------------------------

    def record_failure(self, error: str, max_length: int = 4000) -> None:
        """
        Record a failed attempt.

        Increments the attempt counter and stores a truncated error message
        for context in the next retry. Full output is preserved in logs/.

        Args:
            error: Error message from the failed attempt.
            max_length: Maximum characters to store (default 4000). Prevents
                prompt size from exceeding shell argument limits (~128KB).
        """
        self.attempt += 1
        if len(error) > max_length:
            self.last_failure = (
                error[:max_length] + "\n\n[... truncated, see logs/ for full output]"
            )
        else:
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
    # Stage timing methods
    # -------------------------------------------------------------------------

    def start_stage_timer(self) -> None:
        """
        Start timing for the current stage.

        Records the current timestamp in ISO format. Called when a stage
        begins execution.
        """
        self.stage_start_time = datetime.now(timezone.utc).isoformat()

    def record_stage_duration(self) -> int | None:
        """
        Record the duration of the current stage.

        Calculates elapsed time from stage_start_time and stores it in
        stage_durations dict. Returns the duration in seconds.

        Returns:
            Duration in seconds, or None if no start time was recorded.
        """
        if not self.stage_start_time:
            return None

        try:
            start = datetime.fromisoformat(self.stage_start_time)
            elapsed = int((datetime.now(timezone.utc) - start).total_seconds())

            if self.stage_durations is None:
                self.stage_durations = {}

            self.stage_durations[self.stage.value] = elapsed
            self.stage_start_time = None  # Clear for next stage
            return elapsed
        except (ValueError, TypeError):
            return None

    def get_stage_duration(self, stage: "Stage") -> int | None:
        """
        Get the recorded duration for a stage.

        Args:
            stage: The stage to get duration for.

        Returns:
            Duration in seconds, or None if not recorded.
        """
        if self.stage_durations is None:
            return None
        return self.stage_durations.get(stage.value)

    # -------------------------------------------------------------------------
    # Rollback management methods
    # -------------------------------------------------------------------------

    def record_rollback(self, from_stage: Stage, to_stage: Stage, reason: str) -> None:
        """
        Record a rollback event in the history.

        Called when validation fails and triggers a rollback to an earlier stage.
        The history is used to detect rollback loops and prevent infinite retries.
        Keeps only the last 50 events to prevent state growth.

        Args:
            from_stage: Stage that failed and triggered the rollback.
            to_stage: Target stage to roll back to.
            reason: Description of why the rollback was needed.
        """
        event = RollbackEvent.create(from_stage, to_stage, reason)
        self.rollback_history.append(event)
        # Keep only the last 50 events - plenty for the 1-hour window check
        if len(self.rollback_history) > 50:
            self.rollback_history = self.rollback_history[-50:]

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
            r
            for r in self.rollback_history
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

        return len(
            [
                r
                for r in self.rollback_history
                if r.to_stage == target_stage.value and r.timestamp > cutoff_str
            ]
        )

    # -------------------------------------------------------------------------
    # Fast-track rollback methods
    # -------------------------------------------------------------------------

    def record_passed_stage(self, stage: Stage) -> None:
        """
        Record that a stage has passed in the current iteration.

        Called when a stage completes successfully. Used to track which
        stages can be skipped on a minor rollback.

        Args:
            stage: The stage that passed.
        """
        self.passed_stages.add(stage.value)

    def clear_passed_stages(self, preserve_marked: bool = False) -> None:
        """
        Clear the passed stages tracking.

        Called when entering DEV stage to start fresh tracking,
        or on a full rollback (REQUEST_CHANGES).

        Args:
            preserve_marked: If True, keep stages that have preserve_on_rollback=True
                in their metadata (e.g., TEST stage - tests don't need rewriting).
        """
        if preserve_marked:
            # Keep stages marked with preserve_on_rollback=True
            preserved = {
                stage.value
                for stage in Stage
                if STAGE_METADATA.get(stage, StageMetadata("", "")).preserve_on_rollback
            }
            self.passed_stages = self.passed_stages & preserved
        else:
            self.passed_stages = set()

    def setup_fast_track(self) -> None:
        """
        Setup fast-track skipping from passed stages.

        Called on a minor rollback (REQUEST_MINOR_CHANGES). Copies
        passed_stages to fast_track_skip so those stages will be
        skipped on the re-run.
        """
        self.fast_track_skip = self.passed_stages.copy()
        # Don't clear passed_stages - we'll clear it when entering DEV

    def clear_fast_track(self) -> None:
        """
        Clear fast-track skipping.

        Called when workflow completes or on a full rollback.
        """
        self.fast_track_skip = set()

    def should_fast_track_skip(self, stage: Stage) -> bool:
        """
        Check if a stage should be skipped due to fast-track.

        Args:
            stage: The stage to check.

        Returns:
            True if the stage is in fast_track_skip set.
        """
        return stage.value in self.fast_track_skip

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value
        d["task_type"] = self.task_type.value
        # rollback_history is already converted to list of dicts by asdict
        # Convert sets to lists for JSON serialization
        d["passed_stages"] = list(self.passed_stages)
        d["fast_track_skip"] = list(self.fast_track_skip)
        # Convert lineage objects to dicts
        d["artifact_lineage"] = {
            name: lineage.to_dict() if hasattr(lineage, "to_dict") else lineage
            for name, lineage in self.artifact_lineage.items()
        }
        d["stage_lineage"] = {
            name: lineage.to_dict() if hasattr(lineage, "to_dict") else lineage
            for name, lineage in self.stage_lineage.items()
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkflowState":
        # Parse rollback history if present
        rollback_history = [RollbackEvent.from_dict(r) for r in d.get("rollback_history", [])]

        # Parse artifact lineage if present
        artifact_lineage: dict[str, Any] = {}
        for name, data in d.get("artifact_lineage", {}).items():
            if isinstance(data, dict):
                from galangal.core.lineage import ArtifactLineage

                artifact_lineage[name] = ArtifactLineage.from_dict(data)
            else:
                artifact_lineage[name] = data

        # Parse stage lineage if present
        stage_lineage: dict[str, Any] = {}
        for name, data in d.get("stage_lineage", {}).items():
            if isinstance(data, dict):
                from galangal.core.lineage import StageLineage

                stage_lineage[name] = StageLineage.from_dict(data)
            else:
                stage_lineage[name] = data

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
            qa_rounds=d.get("qa_rounds"),
            qa_complete=d.get("qa_complete", False),
            stage_plan=d.get("stage_plan"),
            stage_start_time=d.get("stage_start_time"),
            stage_durations=d.get("stage_durations"),
            github_issue=d.get("github_issue"),
            github_repo=d.get("github_repo"),
            screenshots=d.get("screenshots"),
            passed_stages=set(d.get("passed_stages", [])),
            fast_track_skip=set(d.get("fast_track_skip", [])),
            base_commit_sha=d.get("base_commit_sha"),
            stage_commits=d.get("stage_commits"),
            artifact_lineage=artifact_lineage,
            stage_lineage=stage_lineage,
        )

    @classmethod
    def new(
        cls,
        description: str,
        task_name: str,
        task_type: TaskType = TaskType.FEATURE,
        github_issue: int | None = None,
        github_repo: str | None = None,
        screenshots: list[str] | None = None,
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
            github_issue=github_issue,
            github_repo=github_repo,
            screenshots=screenshots,
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
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # ValueError can occur from Stage.from_str or TaskType.from_str
        # with invalid/unknown values in a corrupted or manually edited state.json
        print(f"Error loading state: {e}")
        return None


def save_state(state: WorkflowState) -> None:
    """Save workflow state for a task."""
    task_dir = get_task_dir(state.task_name)
    task_dir.mkdir(parents=True, exist_ok=True)
    state_file = task_dir / "state.json"
    with open(state_file, "w") as f:
        json.dump(state.to_dict(), f, indent=2)

    # Notify hub if connected
    from galangal.hub.hooks import notify_state_saved

    notify_state_saved(state)
