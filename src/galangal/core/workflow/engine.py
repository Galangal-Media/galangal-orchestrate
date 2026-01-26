"""
Workflow engine - pure state machine logic separated from UI concerns.

The WorkflowEngine encapsulates all workflow state transitions and decision
logic, emitting events that describe what happened. The TUI layer subscribes
to these events and translates them to visual updates.

This separation enables:
- Testing workflow logic without UI
- Alternative UIs (CLI, web, etc.)
- Clearer reasoning about state transitions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from galangal.config.loader import get_config
from galangal.config.schema import GalangalConfig
from galangal.core.artifacts import artifact_exists, parse_stage_plan, read_artifact, write_artifact
from galangal.core.state import (
    STAGE_ORDER,
    Stage,
    WorkflowState,
    get_decision_file_name,
    get_decision_words,
    save_state,
)
from galangal.core.workflow.core import (
    append_rollback_entry,
    archive_rollback_if_exists,
    get_next_stage,
    handle_rollback,
)
from galangal.core.workflow.core import (
    execute_stage as _execute_stage,
)
from galangal.results import StageResult, StageResultType

if TYPE_CHECKING:
    from galangal.ai.base import PauseCheck
    from galangal.ui.tui import WorkflowTUIApp


# =============================================================================
# Workflow Events - what the engine tells the UI
# =============================================================================


class EventType(Enum):
    """Types of events emitted by the workflow engine."""

    # Stage lifecycle
    STAGE_STARTED = auto()
    STAGE_COMPLETED = auto()
    STAGE_FAILED = auto()

    # User interaction required
    APPROVAL_REQUIRED = auto()
    CLARIFICATION_REQUIRED = auto()
    USER_DECISION_REQUIRED = auto()
    MAX_RETRIES_EXCEEDED = auto()
    PREFLIGHT_FAILED = auto()
    ROLLBACK_BLOCKED = auto()

    # State changes
    ROLLBACK_TRIGGERED = auto()
    STAGE_SKIPPED = auto()
    WORKFLOW_COMPLETE = auto()
    WORKFLOW_PAUSED = auto()

    # Discovery Q&A
    DISCOVERY_QUESTIONS = auto()
    DISCOVERY_COMPLETE = auto()


@dataclass
class WorkflowEvent:
    """
    Event emitted by the workflow engine.

    Events describe what happened in the workflow. The TUI layer
    subscribes to these and translates them to visual updates.
    """

    type: EventType
    stage: Stage | None = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def event(
    event_type: EventType,
    stage: Stage | None = None,
    message: str = "",
    **kwargs: Any,
) -> WorkflowEvent:
    """Factory function for creating events."""
    return WorkflowEvent(type=event_type, stage=stage, message=message, data=kwargs)


# =============================================================================
# User Actions - what the UI tells the engine
# =============================================================================


class ActionType(Enum):
    """Types of user actions sent to the workflow engine."""

    # Stage control
    CONTINUE = auto()  # Proceed with workflow
    RETRY = auto()  # Retry current stage
    SKIP = auto()  # Skip current stage (Ctrl+N)
    BACK = auto()  # Go back to previous stage (Ctrl+B)

    # Interrupt
    INTERRUPT = auto()  # Interrupt with feedback (Ctrl+I)
    MANUAL_EDIT = auto()  # Pause for editing (Ctrl+E)

    # Approval/Decision
    APPROVE = auto()  # Approve stage
    REJECT = auto()  # Reject stage
    VIEW_ARTIFACT = auto()  # View full artifact content

    # Workflow control
    QUIT = auto()  # Stop workflow
    FIX_IN_DEV = auto()  # Force rollback to DEV


@dataclass
class UserAction:
    """
    Action from the user to the workflow engine.

    Actions tell the engine what the user wants to do.
    """

    type: ActionType
    data: dict[str, Any] = field(default_factory=dict)


def action(action_type: ActionType, **kwargs: Any) -> UserAction:
    """Factory function for creating actions."""
    return UserAction(type=action_type, data=kwargs)


# =============================================================================
# Workflow Engine
# =============================================================================

# Stages that modify code and should trigger WIP commits when commit_per_stage is enabled
# Note: REVIEW is read-only and doesn't modify code
CODE_MODIFYING_STAGES = {Stage.DEV, Stage.TEST, Stage.DOCS}


class WorkflowEngine:
    """
    Pure state machine for workflow execution.

    The engine encapsulates all workflow logic without any UI knowledge.
    It receives user actions and emits events describing what happened.

    Usage:
        engine = WorkflowEngine(state)

        # Execute a stage
        event = engine.execute_current_stage(tui_app, pause_check)

        # Handle the event based on its type
        if event.type == EventType.APPROVAL_REQUIRED:
            # Collect approval from user via UI
            user_action = action(ActionType.APPROVE, approver="John")
            event = engine.handle_action(user_action)

    The TUI layer is responsible for:
    - Displaying events visually
    - Collecting user input
    - Translating input to UserAction objects
    """

    def __init__(self, state: WorkflowState, config: GalangalConfig | None = None):
        """
        Initialize the workflow engine.

        Args:
            state: Current workflow state.
            config: Optional config, loaded from project if not provided.
        """
        self.state = state
        self.config = config or get_config()
        self._pending_result: StageResult | None = None

    @property
    def current_stage(self) -> Stage:
        """Get the current workflow stage."""
        return self.state.stage

    @property
    def is_complete(self) -> bool:
        """Check if workflow is complete."""
        return self.state.stage == Stage.COMPLETE

    @property
    def max_retries(self) -> int:
        """Get max retries from config."""
        return self.config.stages.max_retries

    def check_github_issue(self) -> WorkflowEvent | None:
        """
        Check if linked GitHub issue is still open.

        Returns:
            WorkflowEvent if issue was closed, None otherwise.
        """
        if not self.state.github_issue:
            return None

        try:
            from galangal.github.issues import is_issue_open

            if is_issue_open(self.state.github_issue) is False:
                return event(
                    EventType.WORKFLOW_PAUSED,
                    message=f"GitHub issue #{self.state.github_issue} has been closed",
                    reason="github_issue_closed",
                )
        except Exception:
            pass  # Non-critical

        return None

    def start_stage_timer(self) -> None:
        """Start timing the current stage if not already started."""
        if not self.state.stage_start_time:
            self.state.start_stage_timer()
            save_state(self.state)

    def execute_current_stage(
        self,
        tui_app: WorkflowTUIApp,
        pause_check: PauseCheck | None = None,
    ) -> WorkflowEvent:
        """
        Execute the current stage and return an event describing the result.

        This is a blocking operation that invokes the AI backend.

        Args:
            tui_app: TUI app for progress display (passed to execute_stage).
            pause_check: Callback returning True if pause requested.

        Returns:
            WorkflowEvent describing the execution result.
        """
        result = _execute_stage(self.state, tui_app=tui_app, pause_check=pause_check)
        self._pending_result = result
        return self._process_stage_result(result)

    def _process_stage_result(self, result: StageResult) -> WorkflowEvent:
        """Convert a StageResult to a WorkflowEvent."""
        stage = self.state.stage

        if result.type == StageResultType.PAUSED:
            return event(EventType.WORKFLOW_PAUSED, stage=stage, reason="user_paused")

        if result.success:
            # Check if approval is needed
            metadata = stage.metadata
            if metadata.requires_approval and metadata.approval_artifact:
                if not artifact_exists(metadata.approval_artifact, self.state.task_name):
                    return event(
                        EventType.APPROVAL_REQUIRED,
                        stage=stage,
                        artifact_name=metadata.approval_artifact,
                    )
            return event(EventType.STAGE_COMPLETED, stage=stage, message=result.message)

        # Handle different failure types
        if result.type == StageResultType.PREFLIGHT_FAILED:
            return event(
                EventType.PREFLIGHT_FAILED,
                stage=stage,
                message=result.message,
                details=result.output or "",
            )

        if result.type == StageResultType.CLARIFICATION_NEEDED:
            questions = self._parse_questions()
            return event(
                EventType.CLARIFICATION_REQUIRED,
                stage=stage,
                questions=questions,
            )

        if result.type == StageResultType.USER_DECISION_NEEDED:
            return event(
                EventType.USER_DECISION_REQUIRED,
                stage=stage,
                message=result.message,
                artifact_preview=(result.output or "")[:500],
                full_content=result.output or "",
            )

        if result.type == StageResultType.ROLLBACK_REQUIRED:
            # Try to process rollback
            if handle_rollback(self.state, result):
                # Include fast-track info in message for visibility
                fast_track_msg = ""
                if result.is_fast_track:
                    skipped = sorted(self.state.fast_track_skip)
                    if skipped:
                        fast_track_msg = f" [FAST-TRACK: skipping {', '.join(skipped)}]"
                return event(
                    EventType.ROLLBACK_TRIGGERED,
                    stage=stage,
                    message=result.message + fast_track_msg,
                    from_stage=stage,
                    to_stage=result.rollback_to,
                    is_fast_track=result.is_fast_track,
                )
            else:
                # Rollback was blocked (loop detection)
                rollback_count = (
                    self.state.get_rollback_count(result.rollback_to) if result.rollback_to else 0
                )
                target = result.rollback_to.value if result.rollback_to else "None"

                if rollback_count >= 3:
                    block_reason = f"Too many rollbacks to {target} ({rollback_count} in last hour)"
                elif result.rollback_to is None:
                    block_reason = "Rollback target not specified in validation"
                else:
                    block_reason = "Rollback blocked (unknown reason)"

                return event(
                    EventType.ROLLBACK_BLOCKED,
                    stage=stage,
                    message=result.message,
                    block_reason=block_reason,
                    target_stage=target,
                )

        # Generic failure - check retries
        error_message = result.output or result.message
        self.state.record_failure(error_message)

        if not self.state.can_retry(self.max_retries):
            return event(
                EventType.MAX_RETRIES_EXCEEDED,
                stage=stage,
                message=error_message,
                attempts=self.state.attempt,
                max_retries=self.max_retries,
                error_context=result.error_context,
            )

        return event(
            EventType.STAGE_FAILED,
            stage=stage,
            message=error_message,
            attempt=self.state.attempt,
            max_retries=self.max_retries,
            error_context=result.error_context,
        )

    def _parse_questions(self) -> list[str]:
        """Parse questions from QUESTIONS.md artifact."""
        content = read_artifact("QUESTIONS.md", self.state.task_name)
        if not content:
            return []

        import re

        questions = []
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("# "):
                continue

            # Numbered or bulleted questions
            match = re.match(r"^\d+[\.\)]\s*(.+)$", line)
            if match:
                questions.append(match.group(1))
            elif line.startswith("- ") or line.startswith("* "):
                questions.append(line[2:].strip())
            elif line.startswith("## "):
                questions.append(line[3:].strip())

        return questions

    def handle_action(
        self, user_action: UserAction, tui_app: WorkflowTUIApp | None = None
    ) -> WorkflowEvent:
        """
        Handle a user action and return the resulting event.

        Args:
            user_action: The action from the user.
            tui_app: Optional TUI app for archive notifications.

        Returns:
            WorkflowEvent describing what happened.
        """
        action_type = user_action.type
        data = user_action.data

        if action_type == ActionType.CONTINUE:
            return self._advance_to_next_stage(tui_app)

        if action_type == ActionType.RETRY:
            # Just continue - the loop will retry the same stage
            save_state(self.state)
            return event(
                EventType.STAGE_STARTED,
                stage=self.state.stage,
                attempt=self.state.attempt,
            )

        if action_type == ActionType.SKIP:
            return self._handle_skip()

        if action_type == ActionType.BACK:
            return self._handle_back()

        if action_type == ActionType.INTERRUPT:
            return self._handle_interrupt(
                feedback=data.get("feedback", ""),
                target_stage=data.get("target_stage"),
            )

        if action_type == ActionType.MANUAL_EDIT:
            # Just return an event - TUI handles the pause
            return event(EventType.WORKFLOW_PAUSED, reason="manual_edit")

        if action_type == ActionType.APPROVE:
            return self._handle_approval(
                approved=True,
                approver=data.get("approver", ""),
            )

        if action_type == ActionType.REJECT:
            return self._handle_approval(
                approved=False,
                reason=data.get("reason", ""),
            )

        if action_type == ActionType.QUIT:
            save_state(self.state)
            return event(EventType.WORKFLOW_PAUSED, reason="user_quit")

        if action_type == ActionType.FIX_IN_DEV:
            return self._handle_fix_in_dev(data.get("error", ""), data.get("feedback", ""))

        # Unknown action
        return event(EventType.WORKFLOW_PAUSED, reason="unknown_action")

    def _advance_to_next_stage(self, tui_app: WorkflowTUIApp | None = None) -> WorkflowEvent:
        """Advance to the next stage after success."""
        current = self.state.stage

        # Record duration and passed stage
        duration = self.state.record_stage_duration()
        self.state.record_passed_stage(current)

        # Record stage lineage if enabled
        self._record_stage_lineage(current)

        # Create stage commit if enabled and this is a code-modifying stage
        if current in CODE_MODIFYING_STAGES:
            if self.config.stages.commit_per_stage:
                self._create_stage_commit(current, tui_app)
            elif tui_app:
                tui_app.add_activity("Skipping commit (commit_per_stage=False)", "ℹ️")

        # Archive rollback after successful DEV
        if current == Stage.DEV and tui_app:
            archive_rollback_if_exists(self.state.task_name, tui_app)
            self.state.clear_passed_stages()

        # Find next stage
        next_stage = get_next_stage(current, self.state)
        skipped_stages = self._get_skipped_stages(current, next_stage)

        if next_stage:
            self.state.stage = next_stage
            self.state.reset_attempts()
            self.state.awaiting_approval = False
            self.state.clarification_required = False
            save_state(self.state)

            return event(
                EventType.STAGE_STARTED,
                stage=next_stage,
                attempt=self.state.attempt,
                skipped_stages=skipped_stages,
                duration=duration,
            )
        else:
            self.state.stage = Stage.COMPLETE
            self.state.clear_fast_track()
            self.state.clear_passed_stages()
            save_state(self.state)
            return event(EventType.WORKFLOW_COMPLETE, duration=duration)

    def _get_skipped_stages(self, current: Stage, next_stage: Stage | None) -> list[Stage]:
        """Get list of stages that were skipped between current and next."""
        if next_stage is None:
            return []

        current_idx = STAGE_ORDER.index(current)
        next_idx = STAGE_ORDER.index(next_stage)

        if next_idx > current_idx + 1:
            return STAGE_ORDER[current_idx + 1 : next_idx]
        return []

    def _record_stage_lineage(self, stage: Stage) -> None:
        """Record lineage for a completed stage.

        Args:
            stage: The stage that just completed.
        """
        if not self.config.lineage.enabled:
            return

        try:
            from galangal.core.lineage import LineageTracker, load_task_artifacts

            artifacts = load_task_artifacts(self.state.task_name)
            tracker = LineageTracker(self.config.lineage)
            tracker.record_stage(stage.value, artifacts, self.state)
            save_state(self.state)
        except Exception:
            # Lineage tracking failures should not break workflow
            pass

    def _create_stage_commit(self, stage: Stage, tui_app: WorkflowTUIApp | None) -> None:
        """Create a WIP commit for a code-modifying stage.

        Args:
            stage: The stage that just completed.
            tui_app: Optional TUI app for activity notifications.
        """
        from galangal.config.loader import get_project_root
        from galangal.core.git_utils import create_wip_commit, has_changes_to_commit

        project_root = get_project_root()

        if tui_app:
            tui_app.add_activity("Checking for changes", "🔍")

        # Check if there are changes first (for better logging)
        has_changes = has_changes_to_commit(project_root)

        if not has_changes:
            if tui_app:
                tui_app.add_activity(f"No code changes to commit for {stage.value}", "ℹ️")
            return

        sha, error = create_wip_commit(
            stage=stage.value,
            task_name=self.state.task_name,
            cwd=project_root,
        )

        if sha:
            # Track the commit in state
            if self.state.stage_commits is None:
                self.state.stage_commits = []
            self.state.stage_commits.append({"stage": stage.value, "sha": sha})
            save_state(self.state)

            if tui_app:
                tui_app.add_activity(f"Committed {stage.value}: {sha[:7]}", "📝")
        elif error:
            # Commit failed with a specific error (likely pre-commit hook)
            from galangal.logging import get_logger

            logger = get_logger(__name__)
            logger.warning(
                "commit_failed",
                stage=stage.value,
                task=self.state.task_name,
                error=error,
            )
            if tui_app:
                tui_app.add_activity(f"Failed to commit {stage.value}: {error[:100]}", "⚠️")

    def _handle_skip(self) -> WorkflowEvent:
        """Handle skip stage action (Ctrl+N)."""
        skipped_stage = self.state.stage
        next_stage = get_next_stage(self.state.stage, self.state)

        if next_stage:
            self.state.stage = next_stage
            self.state.reset_attempts()
            save_state(self.state)
            return event(
                EventType.STAGE_SKIPPED,
                stage=skipped_stage,
                next_stage=next_stage,
            )
        else:
            self.state.stage = Stage.COMPLETE
            save_state(self.state)
            return event(EventType.WORKFLOW_COMPLETE)

    def _handle_back(self) -> WorkflowEvent:
        """Handle back stage action (Ctrl+B)."""
        current_idx = STAGE_ORDER.index(self.state.stage)
        if current_idx > 0:
            prev_stage = STAGE_ORDER[current_idx - 1]
            self.state.stage = prev_stage
            self.state.reset_attempts()
            save_state(self.state)
            return event(
                EventType.STAGE_STARTED,
                stage=prev_stage,
                attempt=self.state.attempt,
            )
        else:
            # Already at first stage
            return event(
                EventType.STAGE_STARTED,
                stage=self.state.stage,
                message="Already at first stage",
            )

    def _handle_interrupt(self, feedback: str, target_stage: Stage | None) -> WorkflowEvent:
        """Handle interrupt with feedback (Ctrl+I)."""
        interrupted_stage = self.state.stage

        # Determine valid rollback targets
        current_idx = STAGE_ORDER.index(interrupted_stage)
        valid_targets = [s for s in STAGE_ORDER[:current_idx] if s != Stage.PREFLIGHT]

        # Use provided target or determine default
        if target_stage is None:
            if interrupted_stage == Stage.PM:
                target_stage = Stage.PM
            elif interrupted_stage == Stage.DESIGN:
                target_stage = Stage.PM
            else:
                target_stage = Stage.DEV

        # Validate target is in valid targets
        if valid_targets and target_stage not in valid_targets:
            target_stage = valid_targets[0] if valid_targets else interrupted_stage

        # Append to ROLLBACK.md
        append_rollback_entry(
            task_name=self.state.task_name,
            source=f"User interrupt (Ctrl+I) during {interrupted_stage.value}",
            from_stage=interrupted_stage.value,
            target_stage=target_stage.value,
            reason=feedback or "No details provided",
        )

        self.state.stage = target_stage
        self.state.last_failure = f"Interrupt feedback from {interrupted_stage.value}: {feedback}"
        self.state.reset_attempts(clear_failure=False)
        save_state(self.state)

        # Log mistake for future reference (user interrupts are valuable feedback)
        self._log_interrupt_mistake(
            task_name=self.state.task_name,
            stage=interrupted_stage.value,
            feedback=feedback,
        )

        return event(
            EventType.ROLLBACK_TRIGGERED,
            stage=interrupted_stage,
            message=f"Interrupted - rolling back to {target_stage.value}",
            from_stage=interrupted_stage,
            to_stage=target_stage,
        )

    def _log_interrupt_mistake(self, task_name: str, stage: str, feedback: str) -> None:
        """Log an interrupt as a mistake for future learning."""
        try:
            from galangal.mistakes import MistakeTracker

            if not feedback:
                return  # No feedback means nothing to learn from

            tracker = MistakeTracker()

            # Extract description from feedback
            description = feedback.split(".")[0].strip()
            if len(description) > 100:
                description = description[:100] + "..."

            tracker.log(
                description=description,
                feedback=feedback,
                stage=stage,
                task=task_name,
            )
        except ImportError:
            pass
        except Exception:
            pass

    def _handle_approval(
        self, approved: bool, approver: str = "", reason: str = ""
    ) -> WorkflowEvent:
        """Handle approval decision."""
        stage = self.state.stage
        metadata = stage.metadata
        approval_artifact = metadata.approval_artifact

        if approved and approver:
            from galangal.core.utils import now_formatted

            content = f"""# {stage.value} Approval

- **Status:** Approved
- **Approved By:** {approver}
- **Date:** {now_formatted()}
"""
            if approval_artifact:
                write_artifact(approval_artifact, content, self.state.task_name)

            # PM-specific: Parse and store stage plan
            if stage == Stage.PM:
                stage_plan = parse_stage_plan(self.state.task_name)
                if stage_plan:
                    self.state.stage_plan = stage_plan
                    save_state(self.state)

            return event(
                EventType.STAGE_COMPLETED,
                stage=stage,
                message=f"Approved by {approver}",
                approver=approver,
            )

        else:
            # Rejected
            self.state.last_failure = f"{stage.value} rejected: {reason}"
            self.state.reset_attempts(clear_failure=False)
            save_state(self.state)

            return event(
                EventType.STAGE_FAILED,
                stage=stage,
                message=f"Rejected: {reason}",
                reason=reason,
            )

    def _handle_fix_in_dev(self, error: str, feedback: str = "") -> WorkflowEvent:
        """Force rollback to DEV with feedback."""
        original_stage = self.state.stage.value

        # Clear rollback history for DEV to allow rollback
        self.state.rollback_history = [
            r for r in self.state.rollback_history if r.to_stage != Stage.DEV.value
        ]

        self.state.stage = Stage.DEV
        self.state.last_failure = (
            f"Manual rollback from {original_stage}: {feedback or error[:500]}"
        )
        self.state.reset_attempts(clear_failure=False)
        save_state(self.state)

        return event(
            EventType.ROLLBACK_TRIGGERED,
            message="Manual rollback to DEV",
            from_stage=Stage.from_str(original_stage),
            to_stage=Stage.DEV,
        )

    def handle_user_decision(
        self,
        choice: str,
        tui_app: WorkflowTUIApp | None = None,
    ) -> WorkflowEvent:
        """
        Handle user decision for stages requiring manual approval.

        Args:
            choice: "approve", "reject", or "quit"
            tui_app: Optional TUI app for archive notifications.

        Returns:
            WorkflowEvent describing the result.
        """
        from galangal.logging import workflow_logger

        stage = self.state.stage

        if choice == "approve":
            # Write decision file
            decision_file = get_decision_file_name(stage)
            approve_word, _ = get_decision_words(stage)
            if decision_file and approve_word:
                write_artifact(decision_file, approve_word, self.state.task_name)
            else:
                decision_file = f"{stage.value.upper()}_DECISION"
                write_artifact(decision_file, "APPROVE", self.state.task_name)

            workflow_logger.user_decision(
                stage=stage.value,
                task_name=self.state.task_name,
                decision="approve",
                reason="decision file missing",
            )

            # Record and advance
            self.state.record_stage_duration()
            self.state.record_passed_stage(stage)

            return self._advance_to_next_stage(tui_app)

        elif choice == "reject":
            # Write rejection decision
            original_stage = stage.value
            decision_file = get_decision_file_name(stage)
            _, reject_word = get_decision_words(stage)
            if decision_file and reject_word:
                write_artifact(decision_file, reject_word, self.state.task_name)
            else:
                decision_file = f"{original_stage.upper()}_DECISION"
                write_artifact(decision_file, "REQUEST_CHANGES", self.state.task_name)

            workflow_logger.user_decision(
                stage=original_stage,
                task_name=self.state.task_name,
                decision="reject",
                reason="decision file missing",
            )

            # Rollback to DEV
            self.state.last_failure = f"User rejected {original_stage} stage"
            self.state.stage = Stage.DEV
            self.state.reset_attempts(clear_failure=False)
            save_state(self.state)

            return event(
                EventType.ROLLBACK_TRIGGERED,
                stage=Stage.from_str(original_stage),
                message="User rejected - rolling back to DEV",
                from_stage=Stage.from_str(original_stage),
                to_stage=Stage.DEV,
            )

        else:  # quit
            workflow_logger.user_decision(
                stage=stage.value,
                task_name=self.state.task_name,
                decision="quit",
                reason="decision file missing",
            )
            save_state(self.state)
            return event(EventType.WORKFLOW_PAUSED, reason="user_quit")

    def handle_clarification_answers(
        self, questions: list[str], answers: list[str]
    ) -> WorkflowEvent:
        """
        Handle answers to clarification questions.

        Args:
            questions: The questions that were asked.
            answers: User's answers.

        Returns:
            WorkflowEvent to continue workflow.
        """
        # Write ANSWERS.md
        lines = ["# Answers\n", "Responses to clarifying questions.\n\n"]
        for i, (q, a) in enumerate(zip(questions, answers), 1):
            lines.append(f"## Question {i}\n")
            lines.append(f"**Q:** {q}\n\n")
            lines.append(f"**A:** {a}\n\n")

        write_artifact("ANSWERS.md", "".join(lines), self.state.task_name)

        # Clear clarification flag
        self.state.clarification_required = False
        save_state(self.state)

        return event(
            EventType.STAGE_STARTED,
            stage=self.state.stage,
            message="Answers saved - resuming stage",
        )

    def get_valid_interrupt_targets(self) -> list[Stage]:
        """Get valid rollback targets for interrupt."""
        current_idx = STAGE_ORDER.index(self.state.stage)
        valid: list[Stage] = [s for s in STAGE_ORDER[:current_idx] if s != Stage.PREFLIGHT]

        if self.state.stage == Stage.PM:
            return [Stage.PM]
        return valid if valid else [self.state.stage]

    def get_default_interrupt_target(self) -> Stage:
        """Get default rollback target for interrupt."""
        if self.state.stage == Stage.PM:
            return Stage.PM
        elif self.state.stage == Stage.DESIGN:
            return Stage.PM
        else:
            return Stage.DEV
