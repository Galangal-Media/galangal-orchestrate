"""Core workflow components."""

from galangal.core.artifacts import artifact_exists, read_artifact, write_artifact
from galangal.core.state import (
    STAGE_METADATA,
    STAGE_ORDER,
    Stage,
    StageMetadata,
    TaskType,
    WorkflowState,
)
from galangal.core.tasks import get_active_task, list_tasks, set_active_task

__all__ = [
    "Stage",
    "StageMetadata",
    "STAGE_METADATA",
    "TaskType",
    "WorkflowState",
    "STAGE_ORDER",
    "artifact_exists",
    "read_artifact",
    "write_artifact",
    "get_active_task",
    "set_active_task",
    "list_tasks",
]
