"""Tests for artifact lineage tracking."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from galangal.config.schema import (
    ArtifactDependencySpec,
    GalangalConfig,
    LineageConfig,
    StageDependencyConfig,
)
from galangal.core.lineage import (
    ArtifactLineage,
    LineageTracker,
    StageLineage,
    load_task_artifacts,
)
from galangal.core.state import Stage, WorkflowState


def make_state(
    task_name: str = "test-task",
    stage: Stage = Stage.DEV,
) -> WorkflowState:
    """Create a WorkflowState with default values for testing."""
    return WorkflowState(
        task_name=task_name,
        stage=stage,
        attempt=1,
        awaiting_approval=False,
        clarification_required=False,
        last_failure=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        task_description="Test task",
    )


class TestSectionParsing:
    """Tests for markdown section parsing."""

    def test_parse_sections_single_section(self):
        """Test parsing markdown with a single header."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        content = """# Introduction

This is the introduction section.
It has multiple lines.
"""
        sections = tracker.parse_sections(content)

        assert "introduction" in sections
        assert len(sections) == 1

    def test_parse_sections_multiple_sections(self):
        """Test parsing markdown with multiple headers."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        content = """# Requirements

- Requirement 1
- Requirement 2

## Implementation Details

Some details here.

# Constraints

- Constraint 1
"""
        sections = tracker.parse_sections(content)

        assert "requirements" in sections
        assert "implementation-details" in sections
        assert "constraints" in sections
        assert len(sections) == 3

    def test_parse_sections_no_headers(self):
        """Test parsing markdown without headers creates preamble section."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        content = """This is some content without headers.
It should all go in the preamble.
"""
        sections = tracker.parse_sections(content)

        assert "preamble" in sections
        assert len(sections) == 1

    def test_parse_sections_nested_headers(self):
        """Test parsing with nested headers (##, ###)."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        content = """# Main Section

## Subsection A

Content A

### Sub-subsection

Deep content

## Subsection B

Content B
"""
        sections = tracker.parse_sections(content)

        assert "main-section" in sections
        assert "subsection-a" in sections
        assert "sub-subsection" in sections
        assert "subsection-b" in sections

    def test_parse_sections_empty_content(self):
        """Test parsing empty content."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        sections = tracker.parse_sections("")

        # Empty content should result in no sections (or empty preamble)
        assert len(sections) <= 1


class TestNormalization:
    """Tests for section name normalization."""

    def test_normalize_lowercase(self):
        """Test normalization converts to lowercase."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        assert tracker._normalize("Requirements") == "requirements"
        assert tracker._normalize("UPPERCASE") == "uppercase"

    def test_normalize_spaces_to_hyphens(self):
        """Test normalization converts spaces to hyphens."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        assert tracker._normalize("Implementation Details") == "implementation-details"
        assert tracker._normalize("Multiple   Spaces") == "multiple---spaces"

    def test_normalize_strips_whitespace(self):
        """Test normalization strips leading/trailing whitespace."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        assert tracker._normalize("  padded  ") == "padded"


class TestHashing:
    """Tests for content hashing."""

    def test_hash_consistent(self):
        """Test that same content produces same hash."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        content = "Some test content"
        hash1 = tracker._hash(content)
        hash2 = tracker._hash(content)

        assert hash1 == hash2
        assert len(hash1) == 16  # Truncated to 16 chars

    def test_hash_whitespace_normalized(self):
        """Test that whitespace differences don't affect hash."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        content1 = "Some   test    content"
        content2 = "Some test content"
        content3 = "Some\ntest\ncontent"

        hash1 = tracker._hash(content1)
        hash2 = tracker._hash(content2)
        hash3 = tracker._hash(content3)

        # All should normalize to same hash
        assert hash1 == hash2
        assert hash2 == hash3

    def test_hash_different_content(self):
        """Test that different content produces different hash."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)

        hash1 = tracker._hash("Content A")
        hash2 = tracker._hash("Content B")

        assert hash1 != hash2


class TestArtifactLineage:
    """Tests for artifact lineage recording and checking."""

    def test_record_artifact_creates_lineage(self):
        """Test recording artifact creates lineage entry."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        content = """# Requirements

- Req 1
- Req 2
"""
        tracker.record_artifact("SPEC.md", content, "PM", "test-task", state)

        assert "SPEC.md" in state.artifact_lineage
        lineage = state.artifact_lineage["SPEC.md"]
        assert lineage.artifact_name == "SPEC.md"
        assert lineage.generated_by_stage == "PM"
        assert "requirements" in lineage.section_hashes

    def test_record_artifact_tracks_inputs(self):
        """Test recording artifact tracks upstream inputs."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        # First record SPEC.md
        spec_content = """# Requirements

- Req 1

# Constraints

- Constraint 1
"""
        tracker.record_artifact("SPEC.md", spec_content, "PM", "test-task", state)

        # Now record DESIGN.md which depends on SPEC.md
        design_content = """# Architecture

Component design.
"""
        tracker.record_artifact("DESIGN.md", design_content, "DESIGN", "test-task", state)

        # DESIGN.md should have tracked SPEC.md inputs
        lineage = state.artifact_lineage["DESIGN.md"]
        assert "SPEC.md" in lineage.input_hashes

    def test_check_artifact_fresh_when_no_changes(self):
        """Test artifact is fresh when inputs haven't changed."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        spec_content = """# Requirements

- Req 1
"""
        tracker.record_artifact("SPEC.md", spec_content, "PM", "test-task", state)

        design_content = "# Architecture\n\nDesign here."
        tracker.record_artifact("DESIGN.md", design_content, "DESIGN", "test-task", state)

        # Check freshness with unchanged artifacts
        artifacts = {"SPEC.md": spec_content, "DESIGN.md": design_content}
        is_fresh, reasons = tracker.check_artifact_fresh("DESIGN.md", artifacts, state)

        assert is_fresh is True
        assert len(reasons) == 0

    def test_check_artifact_stale_when_input_changed(self):
        """Test artifact is stale when upstream input changed."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        spec_content = """# Requirements

- Req 1
"""
        tracker.record_artifact("SPEC.md", spec_content, "PM", "test-task", state)

        design_content = "# Architecture\n\nDesign here."
        tracker.record_artifact("DESIGN.md", design_content, "DESIGN", "test-task", state)

        # Modify SPEC.md requirements
        modified_spec = """# Requirements

- Req 1
- Req 2 (NEW!)
"""
        artifacts = {"SPEC.md": modified_spec, "DESIGN.md": design_content}
        is_fresh, reasons = tracker.check_artifact_fresh("DESIGN.md", artifacts, state)

        assert is_fresh is False
        assert len(reasons) > 0
        assert any("SPEC.md" in r for r in reasons)


class TestStageLineage:
    """Tests for stage lineage recording and checking."""

    def test_record_stage_creates_lineage(self):
        """Test recording stage creates lineage entry."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        artifacts = {
            "PLAN.md": """# Implementation Steps

1. Step one
2. Step two

# File Changes

- file1.py
"""
        }

        tracker.record_stage("DEV", artifacts, state)

        assert "DEV" in state.stage_lineage
        lineage = state.stage_lineage["DEV"]
        assert lineage.stage == "DEV"
        assert "PLAN.md" in lineage.input_hashes

    def test_check_stage_fresh_when_no_changes(self):
        """Test stage is fresh when inputs haven't changed."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        artifacts = {
            "PLAN.md": "# Implementation Steps\n\nSteps here.",
            "SPEC.md": "# Acceptance Criteria\n\nCriteria here.",
        }

        tracker.record_stage("DEV", artifacts, state)

        is_fresh, reasons = tracker.check_stage_fresh("DEV", artifacts, state)

        assert is_fresh is True
        assert len(reasons) == 0

    def test_check_stage_stale_when_artifact_changed(self):
        """Test stage is stale when dependent artifact changed."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        original_artifacts = {
            "PLAN.md": "# Implementation Steps\n\nSteps here.",
        }
        tracker.record_stage("DEV", original_artifacts, state)

        # Modify the artifact
        modified_artifacts = {
            "PLAN.md": "# Implementation Steps\n\nDifferent steps!",
        }

        is_fresh, reasons = tracker.check_stage_fresh("DEV", modified_artifacts, state)

        assert is_fresh is False
        assert len(reasons) > 0


class TestExternalModificationDetection:
    """Tests for detecting external artifact modifications."""

    def test_detect_no_modifications(self):
        """Test no modifications detected when artifacts unchanged."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        content = "# Test\n\nContent here."
        tracker.record_artifact("TEST.md", content, "DEV", "test-task", state)

        artifacts = {"TEST.md": content}
        mods = tracker.detect_external_mods("test-task", artifacts, state)

        assert len(mods) == 0

    def test_detect_section_modified(self):
        """Test detection of modified section."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        original = "# Test\n\nOriginal content."
        tracker.record_artifact("TEST.md", original, "DEV", "test-task", state)

        modified = "# Test\n\nModified content!"
        artifacts = {"TEST.md": modified}
        mods = tracker.detect_external_mods("test-task", artifacts, state)

        assert "TEST.md" in mods
        assert "test" in mods["TEST.md"]

    def test_detect_new_section_added(self):
        """Test detection of newly added section."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        original = "# Section One\n\nContent."
        tracker.record_artifact("TEST.md", original, "DEV", "test-task", state)

        modified = "# Section One\n\nContent.\n\n# Section Two\n\nNew section!"
        artifacts = {"TEST.md": modified}
        mods = tracker.detect_external_mods("test-task", artifacts, state)

        assert "TEST.md" in mods
        # Should detect the new section
        assert any("new" in s for s in mods["TEST.md"])


class TestCascadePreview:
    """Tests for cascade preview functionality."""

    def test_cascade_preview_empty_when_all_fresh(self):
        """Test cascade is empty when all stages are fresh."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        artifacts = {"SPEC.md": "# Test\n\nContent."}
        tracker.record_stage("PM", artifacts, state)
        tracker.record_stage("DESIGN", artifacts, state)

        cascade = tracker.get_cascade_preview(state, artifacts)

        assert len(cascade) == 0

    def test_cascade_preview_shows_stale_stages(self):
        """Test cascade shows stages with stale inputs."""
        config = LineageConfig(enabled=True)
        tracker = LineageTracker(config)
        state = make_state()

        original_artifacts = {
            "PLAN.md": "# Implementation Steps\n\nOriginal steps.",
        }
        tracker.record_stage("DEV", original_artifacts, state)

        # Modify artifacts
        modified_artifacts = {
            "PLAN.md": "# Implementation Steps\n\nModified steps!",
        }

        cascade = tracker.get_cascade_preview(state, modified_artifacts)

        # DEV should be in cascade as stale
        stale_stages = [stage for stage, _ in cascade]
        assert "DEV" in stale_stages


class TestLineageDataclasses:
    """Tests for lineage dataclass serialization."""

    def test_artifact_lineage_to_dict(self):
        """Test ArtifactLineage serialization."""
        lineage = ArtifactLineage(
            artifact_name="SPEC.md",
            generated_at="2024-01-01T00:00:00Z",
            generated_by_stage="PM",
            section_hashes={"requirements": "abc123"},
            input_hashes={},
            depends_on={},
        )

        d = lineage.to_dict()

        assert d["artifact_name"] == "SPEC.md"
        assert d["generated_by_stage"] == "PM"
        assert d["section_hashes"]["requirements"] == "abc123"

    def test_artifact_lineage_from_dict(self):
        """Test ArtifactLineage deserialization."""
        d = {
            "artifact_name": "SPEC.md",
            "generated_at": "2024-01-01T00:00:00Z",
            "generated_by_stage": "PM",
            "section_hashes": {"requirements": "abc123"},
            "input_hashes": {},
            "depends_on": {},
        }

        lineage = ArtifactLineage.from_dict(d)

        assert lineage.artifact_name == "SPEC.md"
        assert lineage.generated_by_stage == "PM"

    def test_stage_lineage_to_dict(self):
        """Test StageLineage serialization."""
        lineage = StageLineage(
            stage="DEV",
            completed_at="2024-01-01T00:00:00Z",
            input_hashes={"PLAN.md": {"steps": "xyz789"}},
            depends_on_stages=["PM", "DESIGN"],
        )

        d = lineage.to_dict()

        assert d["stage"] == "DEV"
        assert d["depends_on_stages"] == ["PM", "DESIGN"]

    def test_stage_lineage_from_dict(self):
        """Test StageLineage deserialization."""
        d = {
            "stage": "DEV",
            "completed_at": "2024-01-01T00:00:00Z",
            "input_hashes": {"PLAN.md": {"steps": "xyz789"}},
            "depends_on_stages": ["PM", "DESIGN"],
        }

        lineage = StageLineage.from_dict(d)

        assert lineage.stage == "DEV"
        assert lineage.depends_on_stages == ["PM", "DESIGN"]


class TestWorkflowStateSerialization:
    """Tests for lineage fields in WorkflowState serialization."""

    def test_state_with_lineage_to_dict(self):
        """Test WorkflowState with lineage serializes correctly."""
        state = make_state()

        # Add some lineage data
        state.artifact_lineage["SPEC.md"] = ArtifactLineage(
            artifact_name="SPEC.md",
            generated_at="2024-01-01T00:00:00Z",
            generated_by_stage="PM",
            section_hashes={"requirements": "abc123"},
            input_hashes={},
            depends_on={},
        )
        state.stage_lineage["PM"] = StageLineage(
            stage="PM",
            completed_at="2024-01-01T00:00:00Z",
            input_hashes={},
            depends_on_stages=[],
        )

        d = state.to_dict()

        assert "artifact_lineage" in d
        assert "stage_lineage" in d
        assert "SPEC.md" in d["artifact_lineage"]
        assert "PM" in d["stage_lineage"]

    def test_state_with_lineage_from_dict(self):
        """Test WorkflowState with lineage deserializes correctly."""
        d = {
            "stage": "DEV",
            "attempt": 1,
            "awaiting_approval": False,
            "clarification_required": False,
            "last_failure": None,
            "started_at": "2024-01-01T00:00:00Z",
            "task_description": "Test",
            "task_name": "test-task",
            "task_type": "feature",
            "rollback_history": [],
            "artifact_lineage": {
                "SPEC.md": {
                    "artifact_name": "SPEC.md",
                    "generated_at": "2024-01-01T00:00:00Z",
                    "generated_by_stage": "PM",
                    "section_hashes": {"requirements": "abc123"},
                    "input_hashes": {},
                    "depends_on": {},
                }
            },
            "stage_lineage": {
                "PM": {
                    "stage": "PM",
                    "completed_at": "2024-01-01T00:00:00Z",
                    "input_hashes": {},
                    "depends_on_stages": [],
                }
            },
        }

        state = WorkflowState.from_dict(d)

        assert "SPEC.md" in state.artifact_lineage
        assert isinstance(state.artifact_lineage["SPEC.md"], ArtifactLineage)
        assert "PM" in state.stage_lineage
        assert isinstance(state.stage_lineage["PM"], StageLineage)


class TestLineageConfig:
    """Tests for LineageConfig model."""

    def test_lineage_config_defaults(self):
        """Test LineageConfig has correct defaults."""
        config = LineageConfig()

        assert config.enabled is False
        assert config.block_on_staleness is True
        assert config.artifact_dependencies == {}
        assert config.stage_dependencies == {}

    def test_lineage_config_with_custom_deps(self):
        """Test LineageConfig with custom dependencies."""
        config = LineageConfig(
            enabled=True,
            artifact_dependencies={
                "CUSTOM.md": [
                    ArtifactDependencySpec(artifact="SPEC.md", sections=["custom"])
                ]
            },
            stage_dependencies={
                "CUSTOM": StageDependencyConfig(
                    depends_on_stages=["PM"],
                    depends_on_artifacts=[
                        ArtifactDependencySpec(artifact="SPEC.md")
                    ],
                )
            },
        )

        assert config.enabled is True
        assert "CUSTOM.md" in config.artifact_dependencies
        assert "CUSTOM" in config.stage_dependencies

    def test_galangal_config_has_lineage(self):
        """Test GalangalConfig includes lineage field."""
        config = GalangalConfig()

        assert hasattr(config, "lineage")
        assert isinstance(config.lineage, LineageConfig)
        assert config.lineage.enabled is False


class TestLoadTaskArtifacts:
    """Tests for load_task_artifacts utility."""

    def test_load_artifacts_from_directory(self):
        """Test loading artifacts from task directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "test-task"
            task_dir.mkdir(parents=True)

            # Create some artifacts
            (task_dir / "SPEC.md").write_text("# Spec\n\nContent.")
            (task_dir / "PLAN.md").write_text("# Plan\n\nSteps.")
            (task_dir / "not-markdown.txt").write_text("ignored")

            with patch("galangal.core.state.get_task_dir", return_value=task_dir):
                artifacts = load_task_artifacts("test-task")

            assert "SPEC.md" in artifacts
            assert "PLAN.md" in artifacts
            assert "not-markdown.txt" not in artifacts
            assert artifacts["SPEC.md"] == "# Spec\n\nContent."

    def test_load_artifacts_empty_directory(self):
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "test-task"
            task_dir.mkdir(parents=True)

            with patch("galangal.core.state.get_task_dir", return_value=task_dir):
                artifacts = load_task_artifacts("test-task")

            assert artifacts == {}

    def test_load_artifacts_nonexistent_directory(self):
        """Test loading from non-existent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "galangal-tasks" / "nonexistent"

            with patch("galangal.core.state.get_task_dir", return_value=task_dir):
                artifacts = load_task_artifacts("nonexistent")

            assert artifacts == {}
