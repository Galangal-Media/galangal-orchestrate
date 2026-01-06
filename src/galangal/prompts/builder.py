"""
Prompt building with project override support.
"""

from pathlib import Path
from typing import Optional

from galangal.config.loader import get_project_root, get_prompts_dir, get_config
from galangal.core.state import Stage, WorkflowState
from galangal.core.artifacts import artifact_exists, read_artifact


class PromptBuilder:
    """Build prompts for stages with project overrides."""

    def __init__(self):
        self.config = get_config()
        self.project_root = get_project_root()
        self.override_dir = get_prompts_dir()
        self.defaults_dir = Path(__file__).parent / "defaults"

    def get_stage_prompt(self, stage: Stage) -> str:
        """Get the base prompt for a stage, checking overrides first."""
        stage_lower = stage.value.lower()

        # 1. Check for project override
        override_path = self.override_dir / f"{stage_lower}.md"
        if override_path.exists():
            return override_path.read_text()

        # 2. Fall back to default
        default_path = self.defaults_dir / f"{stage_lower}.md"
        if default_path.exists():
            return default_path.read_text()

        # 3. Minimal fallback
        return f"Execute the {stage.value} stage for the task."

    def build_full_prompt(self, stage: Stage, state: WorkflowState) -> str:
        """Build the complete prompt for a stage execution."""
        base_prompt = self.get_stage_prompt(stage)
        task_name = state.task_name

        # Build context
        context_parts = [
            f"# Task: {task_name}",
            f"# Task Type: {state.task_type.display_name()}",
            f"# Description\n{state.task_description}",
            f"\n# Current Stage: {stage.value}",
            f"\n# Attempt: {state.attempt}",
            f"\n# Artifacts Directory: {self.config.tasks_dir}/{task_name}/",
        ]

        # Add failure context
        if state.last_failure:
            context_parts.append(f"\n# Previous Failure\n{state.last_failure}")

        # Add relevant artifacts based on stage
        context_parts.extend(self._get_artifact_context(stage, task_name))

        # Add global prompt context from config
        if self.config.prompt_context:
            context_parts.append(f"\n# Project Context\n{self.config.prompt_context}")

        # Add stage-specific context from config
        stage_context = self.config.stage_context.get(stage.value, "")
        if stage_context:
            context_parts.append(f"\n# Stage Context\n{stage_context}")

        context = "\n".join(context_parts)
        return f"{context}\n\n---\n\n{base_prompt}"

    def _get_artifact_context(self, stage: Stage, task_name: str) -> list[str]:
        """Get relevant artifact content for the stage."""
        parts = []

        # SPEC and PLAN for all stages after PM
        if stage != Stage.PM:
            if artifact_exists("SPEC.md", task_name):
                parts.append(f"\n# SPEC.md\n{read_artifact('SPEC.md', task_name)}")
            if artifact_exists("PLAN.md", task_name):
                parts.append(f"\n# PLAN.md\n{read_artifact('PLAN.md', task_name)}")

        # DESIGN for stages after DESIGN
        if stage not in [Stage.PM, Stage.DESIGN]:
            if artifact_exists("DESIGN.md", task_name):
                parts.append(f"\n# DESIGN.md\n{read_artifact('DESIGN.md', task_name)}")
            elif artifact_exists("DESIGN_SKIP.md", task_name):
                parts.append(
                    f"\n# Note: Design stage was skipped\n{read_artifact('DESIGN_SKIP.md', task_name)}"
                )

        # ROLLBACK for DEV and TEST (issues to fix)
        if stage in [Stage.DEV, Stage.TEST]:
            if artifact_exists("ROLLBACK.md", task_name):
                parts.append(
                    f"\n# ROLLBACK.md (PRIORITY - Fix these issues first!)\n{read_artifact('ROLLBACK.md', task_name)}"
                )
            if artifact_exists("QA_REPORT.md", task_name):
                parts.append(
                    f"\n# QA_REPORT.md (Previous run)\n{read_artifact('QA_REPORT.md', task_name)}"
                )
            if artifact_exists("SECURITY_CHECKLIST.md", task_name):
                parts.append(
                    f"\n# SECURITY_CHECKLIST.md (Previous run)\n{read_artifact('SECURITY_CHECKLIST.md', task_name)}"
                )
            if artifact_exists("REVIEW_NOTES.md", task_name):
                parts.append(
                    f"\n# REVIEW_NOTES.md (Previous run)\n{read_artifact('REVIEW_NOTES.md', task_name)}"
                )

        # TEST_PLAN for TEST and CONTRACT stages
        if stage in [Stage.TEST, Stage.CONTRACT]:
            if artifact_exists("TEST_PLAN.md", task_name):
                parts.append(
                    f"\n# TEST_PLAN.md\n{read_artifact('TEST_PLAN.md', task_name)}"
                )

        # Reports for later stages
        if stage in [Stage.QA, Stage.BENCHMARK, Stage.SECURITY, Stage.REVIEW]:
            if artifact_exists("MIGRATION_REPORT.md", task_name):
                parts.append(
                    f"\n# MIGRATION_REPORT.md\n{read_artifact('MIGRATION_REPORT.md', task_name)}"
                )
            if artifact_exists("CONTRACT_REPORT.md", task_name):
                parts.append(
                    f"\n# CONTRACT_REPORT.md\n{read_artifact('CONTRACT_REPORT.md', task_name)}"
                )

        # For REVIEW, include QA and Security reports
        if stage == Stage.REVIEW:
            if artifact_exists("QA_REPORT.md", task_name):
                parts.append(
                    f"\n# QA_REPORT.md\n{read_artifact('QA_REPORT.md', task_name)}"
                )
            if artifact_exists("SECURITY_CHECKLIST.md", task_name):
                parts.append(
                    f"\n# SECURITY_CHECKLIST.md\n{read_artifact('SECURITY_CHECKLIST.md', task_name)}"
                )

        return parts
