"""
Prompt building with project override support.
"""

from pathlib import Path

from galangal.config.loader import get_config, get_project_root, get_prompts_dir
from galangal.core.artifacts import artifact_exists, read_artifact
from galangal.core.state import Stage, WorkflowState


class PromptBuilder:
    """
    Build prompts for workflow stages with project override support.

    This class constructs prompts by merging:
    1. Base prompts from `galangal/prompts/defaults/` (built into package)
    2. Project prompts from `.galangal/prompts/` (project-specific)
    3. Task context (description, artifacts, state)
    4. Config context (prompt_context, stage_context)

    Project prompts can either:
    - Supplement: Include `# BASE` marker where default prompt is inserted
    - Override: No marker means complete replacement of base prompt

    Example supplement prompt:
        ```markdown
        # Project-Specific Instructions
        Follow our coding style guide.

        # BASE

        # Additional Notes
        Use our custom test framework.
        ```
    """

    def __init__(self):
        self.config = get_config()
        self.project_root = get_project_root()
        self.override_dir = get_prompts_dir()
        self.defaults_dir = Path(__file__).parent / "defaults"

    def get_stage_prompt(self, stage: Stage) -> str:
        """Get the prompt for a stage, with project override/supplement support.

        Project prompts in .galangal/prompts/ can either:
        - Supplement the base: Include '# BASE' marker where base prompt should be inserted
        - Override entirely: No marker = full replacement of base prompt
        """
        stage_lower = stage.value.lower()

        # Get base prompt
        default_path = self.defaults_dir / f"{stage_lower}.md"
        base_prompt = ""
        if default_path.exists():
            base_prompt = default_path.read_text()

        # Check for project prompt
        project_path = self.override_dir / f"{stage_lower}.md"
        if not project_path.exists():
            return base_prompt or f"Execute the {stage.value} stage for the task."

        project_prompt = project_path.read_text()

        # Check for # BASE marker (supplement mode)
        if "# BASE" in project_prompt:
            # Split at marker and insert base prompt
            parts = project_prompt.split("# BASE", 1)
            header = parts[0].rstrip()
            footer = parts[1].lstrip() if len(parts) > 1 else ""

            result_parts = []
            if header:
                result_parts.append(header)
            if base_prompt:
                result_parts.append(base_prompt)
            if footer:
                result_parts.append(footer)

            return "\n\n".join(result_parts)

        # No marker = full override
        return project_prompt

    def build_full_prompt(self, stage: Stage, state: WorkflowState) -> str:
        """
        Build the complete prompt for a stage execution.

        Assembles a full prompt by combining:
        1. Task metadata (name, type, description, attempt)
        2. Relevant artifacts (SPEC.md, PLAN.md, ROLLBACK.md, etc.)
        3. Global prompt_context from config
        4. Stage-specific stage_context from config
        5. Documentation config (for DOCS and SECURITY stages)
        6. The stage prompt (from get_stage_prompt)

        The artifacts included vary by stage - later stages receive more
        context from earlier artifacts.

        Args:
            stage: The workflow stage to build prompt for.
            state: Current workflow state with task info and history.

        Returns:
            Complete prompt string ready for AI invocation.
        """
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

        # Add documentation config for DOCS and SECURITY stages
        if stage in [Stage.DOCS, Stage.SECURITY]:
            docs_config = self.config.docs
            context_parts.append(f"""
# Documentation Configuration
## Paths
- Changelog Directory: {docs_config.changelog_dir}
- Security Audit Directory: {docs_config.security_audit}
- General Documentation: {docs_config.general}

## What to Update
- Update Changelog: {"YES" if docs_config.update_changelog else "NO - Skip changelog updates"}
- Update Security Audit: {"YES" if docs_config.update_security_audit else "NO - Skip security audit docs"}
- Update General Docs: {"YES" if docs_config.update_general_docs else "NO - Skip general documentation"}

Only update documentation types marked as YES above.""")

        context = "\n".join(context_parts)
        return f"{context}\n\n---\n\n{base_prompt}"

    def _get_artifact_context(self, stage: Stage, task_name: str) -> list[str]:
        """
        Get relevant artifact content for inclusion in the stage prompt.

        Different stages need different context:
        - All stages after PM: SPEC.md, PLAN.md
        - After DESIGN: DESIGN.md or DESIGN_SKIP.md
        - DEV: DEVELOPMENT.md (for resume), ROLLBACK.md (issues to fix)
        - TEST: ROLLBACK.md, previous reports
        - Later stages: Various reports (QA, Security, etc.)

        Args:
            stage: Current stage to get context for.
            task_name: Task name for artifact lookups.

        Returns:
            List of formatted artifact sections (e.g., "# SPEC.md\\n{content}").
        """
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

        # DEVELOPMENT.md for DEV stage (progress tracking for resume)
        if stage == Stage.DEV:
            if artifact_exists("DEVELOPMENT.md", task_name):
                parts.append(
                    f"\n# DEVELOPMENT.md (Previous progress - continue from here)\n{read_artifact('DEVELOPMENT.md', task_name)}"
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
