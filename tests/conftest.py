"""
Shared pytest fixtures for galangal tests.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest

from galangal.ai.base import AIBackend, PauseCheck
from galangal.config.schema import GalangalConfig, ProjectConfig, StageConfig
from galangal.core.state import Stage, TaskType, WorkflowState
from galangal.results import StageResult
from galangal.ui.tui import StageUI


class MockAIBackend(AIBackend):
    """
    Mock AI backend for testing.

    Allows specifying responses per stage and tracks all calls made.
    Can also simulate failures and artifact creation.
    """

    def __init__(
        self,
        responses: dict[Stage, StageResult] | None = None,
        default_response: StageResult | None = None,
        artifact_callback: Callable[[Stage, str], None] | None = None,
    ):
        """
        Initialize mock backend.

        Args:
            responses: Dict mapping Stage to StageResult to return.
            default_response: Default response if stage not in responses.
            artifact_callback: Optional callback(stage, task_name) to create artifacts.
        """
        self.responses = responses or {}
        self.default_response = default_response or StageResult.success("Mock success")
        self.artifact_callback = artifact_callback
        self.calls: list[tuple[str, Stage | None, str | None]] = []

    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui: StageUI | None = None,
        pause_check: PauseCheck | None = None,
    ) -> StageResult:
        """Record the call and return configured response."""
        # Try to extract stage from prompt for tracking
        stage = None
        task_name = None

        for s in Stage:
            if s.value in prompt.upper():
                stage = s
                break

        self.calls.append((prompt[:100], stage, task_name))

        # Simulate artifact creation if callback provided
        if self.artifact_callback and stage:
            self.artifact_callback(stage, task_name or "test-task")

        # Check pause request
        if pause_check and pause_check():
            return StageResult.paused()

        # Return configured response
        if stage and stage in self.responses:
            return self.responses[stage]
        return self.default_response

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """Return simple mock text."""
        self.calls.append((prompt[:100], None, None))
        return "mock-generated-text"

    @property
    def name(self) -> str:
        return "mock"


class MockStageUI(StageUI):
    """Mock UI for testing without TUI."""

    def __init__(self):
        self.activities: list[tuple[str, str]] = []
        self.messages: list[tuple[str, str]] = []
        self.files_read: list[str] = []
        self.files_written: list[str] = []

    def add_activity(self, text: str, icon: str = "•") -> None:
        self.activities.append((text, icon))

    def show_message(self, message: str, style: str = "info") -> None:
        self.messages.append((message, style))

    def set_current_action(self, action: str) -> None:
        pass

    def clear_current_action(self) -> None:
        pass

    def add_file_read(self, path: str) -> None:
        self.files_read.append(path)

    def add_file_written(self, path: str) -> None:
        self.files_written.append(path)


@pytest.fixture
def mock_backend():
    """Create a mock AI backend with default success responses."""
    return MockAIBackend()


@pytest.fixture
def mock_ui():
    """Create a mock stage UI."""
    return MockStageUI()


@pytest.fixture
def galangal_project(tmp_path: Path) -> Path:
    """Create a minimal galangal project structure."""
    # Create .galangal directory
    galangal_dir = tmp_path / ".galangal"
    galangal_dir.mkdir()

    # Create config.yaml with defaults
    config_content = """
project:
  name: "Test Project"
  stacks:
    - language: python
      framework: pytest

stages:
  skip: []
  timeout: 14400
  max_retries: 3

logging:
  enabled: false
"""
    (galangal_dir / "config.yaml").write_text(config_content)

    # Create tasks directory
    tasks_dir = tmp_path / "galangal-tasks"
    tasks_dir.mkdir()

    # Create active_task file (empty)
    (galangal_dir / "active_task").write_text("")

    return tmp_path


@pytest.fixture
def sample_task(galangal_project: Path) -> Path:
    """Create a sample task with initial state."""
    task_dir = galangal_project / "galangal-tasks" / "test-task"
    task_dir.mkdir()

    state = WorkflowState(
        stage=Stage.PM,
        attempt=1,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        task_description="Test task description",
        task_name="test-task",
        task_type=TaskType.FEATURE,
    )

    import json

    (task_dir / "state.json").write_text(json.dumps(state.to_dict(), indent=2))

    # Set as active task
    (galangal_project / ".galangal" / "active_task").write_text("test-task")

    return task_dir


@pytest.fixture
def sample_config() -> GalangalConfig:
    """Create a sample GalangalConfig for testing."""
    return GalangalConfig(
        project=ProjectConfig(name="Test Project"),
        stages=StageConfig(skip=[], timeout=14400, max_retries=3),
    )


def make_state(
    task_name: str = "test-task",
    stage: Stage = Stage.PM,
    task_type: TaskType = TaskType.FEATURE,
    attempt: int = 1,
    task_description: str = "Test task",
) -> WorkflowState:
    """Create a WorkflowState with default values for testing."""
    return WorkflowState(
        task_name=task_name,
        stage=stage,
        attempt=attempt,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        task_description=task_description,
        task_type=task_type,
    )


def create_artifact(task_dir: Path, name: str, content: str) -> Path:
    """Create an artifact file in the task directory."""
    artifact_path = task_dir / name
    artifact_path.write_text(content)
    return artifact_path
