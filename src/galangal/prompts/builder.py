"""
Prompt building with project override support.
"""

from pathlib import Path
from typing import Any

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

    def __init__(self) -> None:
        self.config = get_config()
        self.project_root = get_project_root()
        self.override_dir = get_prompts_dir()
        self.defaults_dir = Path(__file__).parent / "defaults"

    def _merge_with_base(self, project_prompt: str, base_prompt: str) -> str:
        """Merge project prompt with base using # BASE marker.

        If project_prompt contains '# BASE', splits around it and inserts
        the base_prompt at that location. Content before the marker becomes
        a header, content after becomes a footer.

        Args:
            project_prompt: Project-specific prompt that may contain # BASE marker.
            base_prompt: Default/base prompt to insert at marker location.

        Returns:
            Merged prompt with base inserted at marker, or project_prompt unchanged
            if no marker present.
        """
        if "# BASE" not in project_prompt:
            return project_prompt

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

    def get_prompt_by_name(self, name: str) -> str:
        """Get a prompt by filename (without .md extension).

        Supports project override/supplement like get_stage_prompt.
        Used for non-stage prompts like 'pm_questions'.

        Args:
            name: Prompt name, e.g., 'pm_questions'

        Returns:
            Prompt content with project overrides applied.
        """
        # Get base prompt
        default_path = self.defaults_dir / f"{name}.md"
        base_prompt = ""
        if default_path.exists():
            base_prompt = default_path.read_text()

        # Check for project prompt
        project_path = self.override_dir / f"{name}.md"
        if not project_path.exists():
            return base_prompt or f"Execute {name}."

        project_prompt = project_path.read_text()

        # Merge with base (returns project_prompt unchanged if no # BASE marker)
        merged = self._merge_with_base(project_prompt, base_prompt)
        if merged != project_prompt:
            return merged

        # No marker = full override
        return project_prompt

    def build_discovery_prompt(
        self, state: WorkflowState, qa_history: list[dict[str, Any]] | None = None
    ) -> str:
        """Build the prompt for PM discovery questions.

        Args:
            state: Current workflow state with task info.
            qa_history: Previous Q&A rounds, if any.

        Returns:
            Complete prompt for generating discovery questions.
        """
        base_prompt = self.get_prompt_by_name("pm_questions")
        task_name = state.task_name

        # Build context
        context_parts = [
            f"# Task: {task_name}",
            f"# Task Type: {state.task_type.display_name()}",
            f"# Brief\n{state.task_description}",
        ]

        # Add screenshot context if available
        context_parts.extend(self._get_screenshot_context(state))

        # Add previous Q&A history
        if qa_history:
            qa_text = self._format_qa_history(qa_history)
            context_parts.append(f"\n# Previous Q&A Rounds\n{qa_text}")
        else:
            context_parts.append("\n# Previous Q&A Rounds\nNone - this is the first round.")

        # Add global prompt context from config
        if self.config.prompt_context:
            context_parts.append(f"\n# Project Context\n{self.config.prompt_context}")

        context = "\n".join(context_parts)
        return f"{context}\n\n---\n\n{base_prompt}"

    def _get_screenshot_context(self, state: WorkflowState) -> list[str]:
        """
        Get screenshot context for inclusion in prompts.

        When screenshots are available from a GitHub issue, instructs the AI
        to read them for visual context (bug reports, designs, etc.).

        Args:
            state: Workflow state containing screenshot paths.

        Returns:
            List of context strings to include in prompt.
        """
        if not state.screenshots:
            return []

        parts = ["\n# Screenshots from GitHub Issue"]
        parts.append(
            "The following screenshots were attached to the GitHub issue. "
            "Use the Read tool to view these images for visual context "
            "(e.g., bug screenshots, design mockups, UI references):"
        )
        for i, path in enumerate(state.screenshots, 1):
            parts.append(f"  {i}. {path}")

        return ["\n".join(parts)]

    def _format_qa_history(self, qa_history: list[dict[str, Any]]) -> str:
        """Format Q&A history for prompt inclusion."""
        parts = []
        for i, round_data in enumerate(qa_history, 1):
            parts.append(f"## Round {i}")
            parts.append("### Questions")
            for j, q in enumerate(round_data.get("questions", []), 1):
                parts.append(f"{j}. {q}")
            parts.append("### Answers")
            for j, a in enumerate(round_data.get("answers", []), 1):
                parts.append(f"{j}. {a}")
            parts.append("")
        return "\n".join(parts)

    def get_stage_prompt(self, stage: Stage, backend_name: str | None = None) -> str:
        """Get the prompt for a stage, with project override/supplement support.

        Project prompts in .galangal/prompts/ can either:
        - Supplement the base: Include '# BASE' marker where base prompt should be inserted
        - Override entirely: No marker = full replacement of base prompt

        Backend-specific prompts are supported. If backend_name is provided,
        the system will first look for {stage}_{backend}.md (e.g., review_codex.md)
        before falling back to the generic {stage}.md prompt.

        Args:
            stage: The workflow stage
            backend_name: Optional backend name for backend-specific prompts
        """
        stage_lower = stage.value.lower()

        # For backend-specific prompts, try {stage}_{backend}.md first
        prompt_names = [stage_lower]
        if backend_name:
            # Insert backend-specific name at the front
            prompt_names.insert(0, f"{stage_lower}_{backend_name}")

        base_prompt = ""
        for prompt_name in prompt_names:
            default_path = self.defaults_dir / f"{prompt_name}.md"
            if default_path.exists():
                base_prompt = default_path.read_text()
                break

        # Check for project prompts (also supports backend-specific)
        for prompt_name in prompt_names:
            project_path = self.override_dir / f"{prompt_name}.md"
            if project_path.exists():
                project_prompt = project_path.read_text()

                # Merge with base (returns project_prompt unchanged if no # BASE marker)
                merged = self._merge_with_base(project_prompt, base_prompt)
                if merged != project_prompt:
                    return merged

                # No marker = full override
                return project_prompt

        return base_prompt or f"Execute the {stage.value} stage for the task."

    def build_full_prompt(
        self, stage: Stage, state: WorkflowState, backend_name: str | None = None
    ) -> str:
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
            backend_name: Optional backend name for backend-specific prompts
                (e.g., "codex" to use review_codex.md instead of review.md).

        Returns:
            Complete prompt string ready for AI invocation.
        """
        base_prompt = self.get_stage_prompt(stage, backend_name)
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

        # Add screenshot context if available (especially useful for PM and early stages)
        if stage in [Stage.PM, Stage.DESIGN, Stage.DEV]:
            context_parts.extend(self._get_screenshot_context(state))

        # Add failure context
        if state.last_failure:
            context_parts.append(f"\n# Previous Failure\n{state.last_failure}")

        # Add relevant artifacts based on stage
        context_parts.extend(self._get_artifact_context(stage, task_name))

        # Add mistake warnings if tracking is available
        mistake_warnings = self._get_mistake_warnings(stage, state)
        if mistake_warnings:
            context_parts.append(mistake_warnings)

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

        # Add decision file info at the END of the prompt for emphasis
        # This ensures the AI sees the critical file creation requirement last
        from galangal.core.state import get_decision_info_for_prompt

        decision_info = get_decision_info_for_prompt(stage)
        decision_suffix = f"\n\n---\n\n{decision_info}" if decision_info else ""

        return f"{context}\n\n---\n\n{base_prompt}{decision_suffix}"

    def _get_artifact_context(self, stage: Stage, task_name: str) -> list[str]:
        """
        Get relevant artifact content for inclusion in the stage prompt.

        Uses config-driven selective filtering if artifact_context is configured,
        otherwise falls back to default stage-specific logic.

        Args:
            stage: Current stage to get context for.
            task_name: Task name for artifact lookups.

        Returns:
            List of formatted artifact sections (e.g., "# SPEC.md\\n{content}").
        """
        # Check if artifact_context is configured for this stage
        if self.config.artifact_context is not None:
            stage_config = getattr(
                self.config.artifact_context, stage.value.lower(), None
            )
            if stage_config and (stage_config.required or stage_config.include):
                return self._get_configured_artifact_context(
                    stage_config, task_name
                )

        # Fall back to default hardcoded logic
        return self._get_default_artifact_context(stage, task_name)

    def _get_configured_artifact_context(
        self, config: "StageArtifactConfig", task_name: str
    ) -> list[str]:
        """
        Get artifact context based on explicit configuration.

        This enables selective context filtering to reduce token usage.

        Args:
            config: Stage artifact configuration with required/include/exclude lists.
            task_name: Task name for artifact lookups.

        Returns:
            List of formatted artifact sections.
        """
        from galangal.config.schema import StageArtifactConfig

        parts = []
        included = set()

        # Process required artifacts (must exist)
        for artifact in config.required:
            if artifact in config.exclude:
                continue
            if artifact_exists(artifact, task_name):
                content = read_artifact(artifact, task_name)
                parts.append(f"\n# {artifact}\n{content}")
                included.add(artifact)

        # Process optional includes (if they exist)
        for artifact in config.include:
            if artifact in included or artifact in config.exclude:
                continue
            if artifact_exists(artifact, task_name):
                content = read_artifact(artifact, task_name)
                parts.append(f"\n# {artifact}\n{content}")
                included.add(artifact)

        return parts

    def _get_default_artifact_context(self, stage: Stage, task_name: str) -> list[str]:
        """
        Get artifact context using default stage-specific logic.

        This is the original hardcoded logic, preserved for backwards compatibility
        when artifact_context is not configured.

        Each stage receives context from earlier artifacts based on what it needs:
        - DESIGN.md supersedes PLAN.md when present
        - If DESIGN was skipped, PLAN.md is included instead
        - Only includes artifacts that exist

        Key inclusion rules:
        - PM: DISCOVERY_LOG.md (Q&A to incorporate into SPEC)
        - DESIGN: SPEC.md only (creates the authoritative implementation plan)
        - DEV+: SPEC.md + DESIGN.md (or PLAN.md if design was skipped)
        - DEV: + DEVELOPMENT.md (resume), ROLLBACK.md (issues to fix)
        - TEST: + TEST_PLAN.md, ROLLBACK.md
        - REVIEW: + QA_REPORT.md, SECURITY_CHECKLIST.md (verify addressed)

        Args:
            stage: Current stage to get context for.
            task_name: Task name for artifact lookups.

        Returns:
            List of formatted artifact sections (e.g., "# SPEC.md\\n{content}").
        """
        parts = []

        # PM stage: only needs discovery Q&A to incorporate into SPEC
        if stage == Stage.PM:
            if artifact_exists("DISCOVERY_LOG.md", task_name):
                parts.append(
                    f"\n# DISCOVERY_LOG.md (User Q&A - use these answers!)\n{read_artifact('DISCOVERY_LOG.md', task_name)}"
                )
            return parts

        # All stages after PM need SPEC (core requirements)
        if artifact_exists("SPEC.md", task_name):
            parts.append(f"\n# SPEC.md\n{read_artifact('SPEC.md', task_name)}")

        # Stages after DESIGN: include DESIGN.md if it exists, otherwise fall back to PLAN.md
        # (DESIGN.md supersedes PLAN.md, but some task types skip DESIGN)
        if stage not in [Stage.PM, Stage.DESIGN]:
            if artifact_exists("DESIGN.md", task_name):
                parts.append(f"\n# DESIGN.md\n{read_artifact('DESIGN.md', task_name)}")
            elif artifact_exists("DESIGN_SKIP.md", task_name):
                parts.append(
                    f"\n# Note: Design stage was skipped\n{read_artifact('DESIGN_SKIP.md', task_name)}"
                )
                # Include PLAN.md as the implementation guide when design was skipped
                if artifact_exists("PLAN.md", task_name):
                    parts.append(f"\n# PLAN.md\n{read_artifact('PLAN.md', task_name)}")

        # DEV stage: progress tracking and rollback issues
        if stage == Stage.DEV:
            if artifact_exists("DEVELOPMENT.md", task_name):
                parts.append(
                    f"\n# DEVELOPMENT.md (Previous progress - continue from here)\n{read_artifact('DEVELOPMENT.md', task_name)}"
                )
            if artifact_exists("ROLLBACK.md", task_name):
                parts.append(
                    f"\n# ROLLBACK.md (PRIORITY - Fix these issues first!)\n{read_artifact('ROLLBACK.md', task_name)}"
                )

        # TEST stage: test plan and rollback issues
        if stage == Stage.TEST:
            if artifact_exists("TEST_PLAN.md", task_name):
                parts.append(f"\n# TEST_PLAN.md\n{read_artifact('TEST_PLAN.md', task_name)}")
            if artifact_exists("ROLLBACK.md", task_name):
                parts.append(
                    f"\n# ROLLBACK.md (Issues to address in tests)\n{read_artifact('ROLLBACK.md', task_name)}"
                )

        # CONTRACT stage: needs test plan for context
        if stage == Stage.CONTRACT:
            if artifact_exists("TEST_PLAN.md", task_name):
                parts.append(f"\n# TEST_PLAN.md\n{read_artifact('TEST_PLAN.md', task_name)}")

        # QA stage: include test summary and test gate results for context
        if stage == Stage.QA:
            if artifact_exists("TEST_SUMMARY.md", task_name):
                parts.append(
                    f"\n# TEST_SUMMARY.md (Test results summary)\n{read_artifact('TEST_SUMMARY.md', task_name)}"
                )
            # Include TEST_GATE_RESULTS.md if test gate ran
            if artifact_exists("TEST_GATE_RESULTS.md", task_name):
                test_gate_content = read_artifact("TEST_GATE_RESULTS.md", task_name)
                parts.append(
                    f"\n# TEST_GATE_RESULTS.md (Automated tests already verified)\n"
                    f"**IMPORTANT:** The following tests have already been run and passed in the TEST_GATE stage. "
                    f"Do NOT re-run these tests - focus on exploratory testing, edge cases, and code quality.\n\n"
                    f"{test_gate_content}"
                )

        # SECURITY stage: include test summary for coverage context
        if stage == Stage.SECURITY:
            if artifact_exists("TEST_SUMMARY.md", task_name):
                parts.append(
                    f"\n# TEST_SUMMARY.md (Test results)\n{read_artifact('TEST_SUMMARY.md', task_name)}"
                )

        # REVIEW stage: needs QA and Security reports to verify they were addressed
        if stage == Stage.REVIEW:
            if artifact_exists("TEST_SUMMARY.md", task_name):
                parts.append(
                    f"\n# TEST_SUMMARY.md (Test results)\n{read_artifact('TEST_SUMMARY.md', task_name)}"
                )
            if artifact_exists("QA_REPORT.md", task_name):
                parts.append(f"\n# QA_REPORT.md\n{read_artifact('QA_REPORT.md', task_name)}")
            if artifact_exists("SECURITY_CHECKLIST.md", task_name):
                parts.append(
                    f"\n# SECURITY_CHECKLIST.md\n{read_artifact('SECURITY_CHECKLIST.md', task_name)}"
                )

        # DOCS stage: include test summary for documentation context
        if stage == Stage.DOCS:
            if artifact_exists("TEST_SUMMARY.md", task_name):
                parts.append(
                    f"\n# TEST_SUMMARY.md (Test results)\n{read_artifact('TEST_SUMMARY.md', task_name)}"
                )

        # SUMMARY stage: needs all artifacts to synthesize a comprehensive summary
        if stage == Stage.SUMMARY:
            # Include test summary
            if artifact_exists("TEST_SUMMARY.md", task_name):
                parts.append(
                    f"\n# TEST_SUMMARY.md (Test results)\n{read_artifact('TEST_SUMMARY.md', task_name)}"
                )
            # Include QA report
            if artifact_exists("QA_REPORT.md", task_name):
                parts.append(f"\n# QA_REPORT.md\n{read_artifact('QA_REPORT.md', task_name)}")
            # Include security checklist
            if artifact_exists("SECURITY_CHECKLIST.md", task_name):
                parts.append(
                    f"\n# SECURITY_CHECKLIST.md\n{read_artifact('SECURITY_CHECKLIST.md', task_name)}"
                )
            # Include review notes
            if artifact_exists("REVIEW_NOTES.md", task_name):
                parts.append(
                    f"\n# REVIEW_NOTES.md\n{read_artifact('REVIEW_NOTES.md', task_name)}"
                )

        return parts

    def _get_mistake_warnings(self, stage: Stage, state: WorkflowState) -> str:
        """
        Get mistake warnings for inclusion in the prompt.

        Retrieves common mistakes from the vector database that are relevant
        to the current stage and task. Returns empty string if mistake tracking
        is not available or no relevant mistakes found.

        Args:
            stage: Current workflow stage.
            state: Current workflow state with task info.

        Returns:
            Formatted warnings string, or empty string if none.
        """
        try:
            from galangal.mistakes import MistakeTracker

            tracker = MistakeTracker()
            return tracker.format_warnings_for_prompt(
                stage=stage.value,
                task_description=state.task_description,
            )
        except ImportError:
            # sentence-transformers not installed
            return ""
        except Exception:
            # Don't fail prompt building if mistake tracking fails
            return ""

    def build_minimal_review_prompt(self, state: WorkflowState, backend_name: str) -> str:
        """
        Build a minimal prompt for independent code review.

        Used for secondary review backends (like Codex) that should give an
        unbiased opinion without being influenced by Claude's interpretations.

        Only includes:
        - Original task description
        - List of changed files with stats
        - Instructions to read files as needed

        Does NOT include:
        - Full git diff (too large for big changes)
        - SPEC.md (Claude's interpretation of requirements)
        - QA_REPORT.md, SECURITY_CHECKLIST.md (previous findings)
        - Any other artifacts from the workflow

        Args:
            state: Workflow state with task info
            backend_name: Backend name for prompt selection (e.g., "codex")

        Returns:
            Minimal prompt for independent review
        """
        import subprocess

        base_branch = self.config.pr.base_branch

        # Get the review prompt (may be backend-specific like review_codex.md)
        review_prompt = self.get_stage_prompt(Stage.REVIEW, backend_name)

        def run_git(*args: str) -> str:
            """Run a git command and return stdout."""
            try:
                result = subprocess.run(
                    ["git", *args],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return result.stdout.strip() if result.returncode == 0 else ""
            except Exception:
                return ""

        # Get file names for the list
        committed_files = run_git("diff", "--name-only", f"{base_branch}...HEAD")
        staged_files = run_git("diff", "--name-only", "--cached")
        unstaged_files = run_git("diff", "--name-only")

        # Combine and deduplicate file names
        all_files = set()
        for files in [committed_files, staged_files, unstaged_files]:
            if files:
                all_files.update(files.split("\n"))
        all_files.discard("")

        files_list = (
            "\n".join(f"- {f}" for f in sorted(all_files)) if all_files else "(No files changed)"
        )

        # Build minimal context - instruct to READ files, not dump diff
        context = f"""# Independent Code Review

## Task
{state.task_description}

## Changed Files
The following files have been modified and need review:

{files_list}

## Instructions
1. Read each changed file listed above to understand the implementation
2. Use `git diff {base_branch}...HEAD -- <file>` to see specific changes if needed
3. Review for code quality, bugs, security issues, and best practices
4. Provide your independent assessment

---

{review_prompt}"""

        return context
