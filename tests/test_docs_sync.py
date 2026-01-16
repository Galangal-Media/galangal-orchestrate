"""
Tests to verify documentation stays in sync with code.

These tests parse documentation files and verify they match the canonical
definitions in state.py. This catches documentation drift.
"""

import re
from pathlib import Path

import pytest

from galangal.core.state import (
    STAGE_METADATA,
    STAGE_ORDER,
    TaskType,
    get_task_type_pipeline,
)


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


class TestReadmeTaskTypes:
    """Verify README task type table matches TASK_TYPE_SKIP_STAGES."""

    def test_readme_task_type_pipelines_match_code(self):
        """
        Verify that the task type table in README.md matches the actual
        stage pipelines derived from TASK_TYPE_SKIP_STAGES.

        This test parses the markdown table and compares each row's pipeline
        with what get_task_type_pipeline() returns.
        """
        readme_path = get_project_root() / "README.md"
        content = readme_path.read_text()

        # Find the Task Types table (starts after "## Task Types")
        # Table format:
        # | Type | Stages | When to Use |
        # |------|--------|-------------|
        # | **Feature** | All stages | New functionality |
        task_types_match = re.search(
            r"## Task Types.*?\n\|[^\n]+\|\n\|[-\s|]+\|\n((?:\|[^\n]+\|\n)+)",
            content,
            re.DOTALL,
        )
        assert task_types_match, "Could not find Task Types table in README.md"

        table_rows = task_types_match.group(1).strip().split("\n")

        # Parse each row and verify
        readme_pipelines: dict[str, str] = {}
        for row in table_rows:
            # Parse: | **Type** | Stages | When to Use |
            cells = [c.strip() for c in row.split("|")[1:-1]]
            if len(cells) >= 2:
                type_name = cells[0].replace("**", "").strip()
                stages = cells[1].strip()
                readme_pipelines[type_name.lower()] = stages

        # Compare with code
        mismatches = []
        for task_type in TaskType:
            type_key = task_type.display_name().lower()
            if type_key == "bug fix":
                type_key = "bug fix"  # README uses "Bug Fix"

            expected_pipeline = get_task_type_pipeline(task_type)
            if task_type == TaskType.FEATURE:
                expected_pipeline = "All stages"

            readme_pipeline = readme_pipelines.get(type_key, "NOT FOUND")

            # Normalize for comparison (README may use different arrow styles)
            readme_normalized = readme_pipeline.replace("→", " → ").replace("  ", " ")
            expected_normalized = expected_pipeline.replace("→", " → ").replace("  ", " ")

            # Check if pipelines match (allow some flexibility in formatting)
            if not self._pipelines_match(readme_normalized, expected_normalized):
                mismatches.append(
                    f"  {task_type.display_name()}:\n"
                    f"    README:   {readme_pipeline}\n"
                    f"    Expected: {expected_pipeline}"
                )

        if mismatches:
            pytest.fail("README task type pipelines don't match code:\n" + "\n".join(mismatches))

    def _pipelines_match(self, readme: str, expected: str) -> bool:
        """
        Check if two pipeline strings match.

        Handles variations in formatting and special cases like "All stages".
        """
        if "All stages" in readme and "All stages" in expected:
            return True

        # Extract stage names and compare
        readme_stages = set(re.findall(r"[A-Z]+", readme))
        expected_stages = set(re.findall(r"[A-Z]+", expected))

        return readme_stages == expected_stages


class TestWorkflowPipelineDoc:
    """Verify workflow-pipeline.md matches code."""

    def test_task_type_skip_table_matches_code(self):
        """
        Verify the task type skip stages table in workflow-pipeline.md
        matches TASK_TYPE_SKIP_STAGES.
        """
        doc_path = get_project_root() / "docs" / "local-development" / "workflow-pipeline.md"
        if not doc_path.exists():
            pytest.skip("workflow-pipeline.md not found")

        content = doc_path.read_text()

        # Find the task type skipping table
        # | Task Type | Skipped Stages |
        skip_table_match = re.search(
            r"\| Task Type \| Skipped Stages \|\n\|[-\s|]+\|\n((?:\|[^\n]+\|\n?)+)",
            content,
        )

        if not skip_table_match:
            pytest.skip("Could not find task type skip table in workflow-pipeline.md")

        # This test just verifies the table exists and has the expected task types
        table_content = skip_table_match.group(1)
        for task_type in TaskType:
            display_name = task_type.display_name().lower()
            # Convert to match doc format (e.g., "bug_fix" -> "bug_fix")
            assert (
                display_name.replace(" ", "_") in table_content.lower()
                or display_name in table_content.lower()
            ), (
                f"Task type '{task_type.display_name()}' not found in workflow-pipeline.md skip table"
            )


class TestStageMetadataConsistency:
    """Verify STAGE_METADATA is complete and consistent."""

    def test_all_stages_have_metadata(self):
        """Every stage in STAGE_ORDER should have metadata."""
        for stage in STAGE_ORDER:
            assert stage in STAGE_METADATA, f"Stage {stage} missing from STAGE_METADATA"

    def test_stage_order_matches_metadata(self):
        """STAGE_ORDER should contain exactly the stages in STAGE_METADATA."""
        order_set = set(STAGE_ORDER)
        metadata_set = set(STAGE_METADATA.keys())
        assert order_set == metadata_set, (
            f"STAGE_ORDER and STAGE_METADATA mismatch:\n"
            f"  In ORDER only: {order_set - metadata_set}\n"
            f"  In METADATA only: {metadata_set - order_set}"
        )

    def test_conditional_stages_have_skip_artifacts(self):
        """Conditional stages should have skip artifacts defined."""
        for stage, metadata in STAGE_METADATA.items():
            if metadata.is_conditional:
                assert metadata.skip_artifact, (
                    f"Conditional stage {stage} should have skip_artifact defined"
                )
