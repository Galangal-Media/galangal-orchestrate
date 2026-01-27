"""
Configuration schema using Pydantic models.
"""

from pydantic import BaseModel, Field, field_validator

from galangal.hub.config import HubConfig


class ProjectConfig(BaseModel):
    """Project-level configuration."""

    name: str = Field(default="My Project", description="Project name")
    approver_name: str | None = Field(
        default=None, description="Default approver name for plan approvals"
    )


class StageConfig(BaseModel):
    """Stage execution configuration."""

    skip: list[str] = Field(default_factory=list, description="Stages to always skip")
    timeout: int = Field(default=14400, description="Stage timeout in seconds (default: 4 hours)")
    max_retries: int = Field(default=5, description="Max retries per stage")
    commit_per_stage: bool = Field(
        default=True,
        description="Create WIP commits after each code-modifying stage, squash at finalization",
    )


class PreflightCheck(BaseModel):
    """A single preflight check."""

    name: str = Field(description="Check name for display")
    command: str | list[str] | None = Field(
        default=None,
        description="Command to run. String uses shell, list runs directly (safer for paths with spaces).",
    )
    path_exists: str | None = Field(default=None, description="Path that must exist")
    expect_empty: bool = Field(default=False, description="Pass if output is empty")
    warn_only: bool = Field(default=False, description="Warn but don't fail the stage")


class TestGateTest(BaseModel):
    """A single test suite configuration for the test gate."""

    name: str = Field(description="Name of the test suite for display")
    command: str = Field(description="Command to run the test suite")
    timeout: int = Field(default=300, description="Timeout in seconds (default: 5 minutes)")


class TestGateConfig(BaseModel):
    """Configuration for the TEST_GATE stage.

    The TEST_GATE stage runs configured test suites and requires all to pass
    before proceeding. This is a mechanical stage (no AI) that acts as a
    quality gate.
    """

    enabled: bool = Field(default=False, description="Enable the test gate stage")
    tests: list[TestGateTest] = Field(
        default_factory=list, description="Test suites to run"
    )
    fail_fast: bool = Field(
        default=True, description="Stop on first test failure instead of running all"
    )

    @field_validator("tests", mode="before")
    @classmethod
    def tests_none_to_list(cls, v: list[TestGateTest] | None) -> list[TestGateTest]:
        """Convert None to empty list (YAML 'tests:' with only comments becomes null)."""
        return v if v is not None else []


class ValidationCommand(BaseModel):
    """A validation command configuration.

    Commands can be specified as a string (shell execution) or list (direct execution).
    List form is preferred when using placeholders like {task_dir} as it handles
    paths with spaces correctly.

    Supported placeholders:
    - {task_dir}: Path to the task directory (galangal-tasks/<task-name>)
    - {project_root}: Path to the project root directory
    - {base_branch}: Configured base branch (e.g., "main")

    Examples:
        # String form (uses shell, supports &&, |, etc.)
        command: "pytest tests/ && ruff check src/"

        # List form (no shell, handles spaces in paths)
        command: ["pytest", "{task_dir}/tests"]
    """

    name: str = Field(description="Command name for display")
    command: str | list[str] = Field(
        description="Command to run. String uses shell, list runs directly (safer for paths with spaces).",
    )
    optional: bool = Field(default=False, description="Don't fail if this command fails")
    allow_failure: bool = Field(default=False, description="Report but don't block on failure")
    timeout: int | None = Field(
        default=None, description="Command timeout in seconds (overrides stage default)"
    )


class SkipCondition(BaseModel):
    """Condition for skipping a stage."""

    no_files_match: str | list[str] | None = Field(
        default=None,
        description="Skip if no files match this glob pattern (or list of patterns)",
    )


class StageValidation(BaseModel):
    """Validation configuration for a single stage."""

    skip_if: SkipCondition | None = Field(default=None, description="Skip condition")
    timeout: int = Field(
        default=300, description="Default timeout in seconds for validation commands"
    )
    commands: list[ValidationCommand] = Field(default_factory=list, description="Commands to run")
    checks: list[PreflightCheck] = Field(
        default_factory=list, description="Preflight checks (for preflight stage)"
    )
    pass_marker: str | None = Field(
        default=None, description="Text marker indicating pass (for AI stages)"
    )
    fail_marker: str | None = Field(
        default=None, description="Text marker indicating failure (for AI stages)"
    )
    artifact: str | None = Field(default=None, description="Artifact file to check for markers")
    artifacts_required: list[str] = Field(
        default_factory=list, description="Required artifact files"
    )


class ValidationConfig(BaseModel):
    """All stage validations."""

    preflight: StageValidation = Field(default_factory=StageValidation)
    migration: StageValidation = Field(default_factory=StageValidation)
    test: StageValidation = Field(default_factory=StageValidation)
    test_gate: StageValidation = Field(default_factory=StageValidation)
    contract: StageValidation = Field(default_factory=StageValidation)
    qa: StageValidation = Field(default_factory=StageValidation)
    security: StageValidation = Field(default_factory=StageValidation)
    review: StageValidation = Field(default_factory=StageValidation)
    docs: StageValidation = Field(default_factory=StageValidation)


class AIBackendConfig(BaseModel):
    """Configuration for an AI backend."""

    command: str = Field(description="Command to invoke the AI")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    max_turns: int = Field(default=200, description="Maximum conversation turns")
    read_only: bool = Field(
        default=False,
        description="Backend runs in read-only mode (cannot write files). "
        "Artifacts will be written from structured output via post-processing.",
    )


class AIConfig(BaseModel):
    """AI backend configuration."""

    default: str = Field(default="claude", description="Default backend")
    backends: dict[str, AIBackendConfig] = Field(
        default_factory=lambda: {
            "claude": AIBackendConfig(
                command="claude",
                args=[
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--max-turns",
                    "{max_turns}",
                    "--permission-mode",
                    "bypassPermissions",
                ],
                max_turns=200,
            ),
            "codex": AIBackendConfig(
                command="codex",
                args=[
                    "exec",
                    "--full-auto",
                    "--output-schema",
                    "{schema_file}",
                    "-o",
                    "{output_file}",
                ],
                max_turns=50,
                read_only=True,
            ),
        }
    )
    stage_backends: dict[str, str] = Field(
        default_factory=dict,
        description="Per-stage backend overrides (e.g., {'REVIEW': 'codex'})",
    )


class DocsConfig(BaseModel):
    """Documentation paths configuration."""

    changelog_dir: str = Field(
        default="docs/changelog",
        description="Directory for changelog entries (organized by year/month)",
    )
    security_audit: str = Field(
        default="docs/security",
        description="Directory for security audit reports",
    )
    general: str = Field(
        default="docs",
        description="Directory for general documentation",
    )
    update_changelog: bool = Field(
        default=True,
        description="Whether to update the changelog during DOCS stage",
    )
    update_security_audit: bool = Field(
        default=True,
        description="Whether to create/update security audit reports during SECURITY stage",
    )
    update_general_docs: bool = Field(
        default=True,
        description="Whether to update general documentation during DOCS stage",
    )


class StageArtifactConfig(BaseModel):
    """Artifact context configuration for a stage.

    Controls which artifacts are included in the prompt context for a stage.
    This enables selective context filtering to reduce token usage.

    Artifacts are checked in order: required → optional → (exclude filters out)
    """

    required: list[str] = Field(
        default_factory=list,
        description="Artifacts that must be included (error if missing)",
    )
    include: list[str] = Field(
        default_factory=list,
        description="Artifacts to include if they exist",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="Artifacts to never include (overrides include)",
    )


class ArtifactContextConfig(BaseModel):
    """Configuration for artifact context filtering per stage.

    Each stage can specify which artifacts it needs. This reduces token usage
    by only including relevant context instead of all accumulated artifacts.

    If a stage is not configured here, it falls back to the default behavior
    (include artifacts based on hardcoded stage logic).
    """

    # Map of stage name (uppercase) to artifact config
    pm: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    design: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    preflight: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    dev: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    migration: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    test: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    test_gate: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    contract: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    qa: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    benchmark: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    security: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    review: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    docs: StageArtifactConfig = Field(default_factory=StageArtifactConfig)
    summary: StageArtifactConfig = Field(default_factory=StageArtifactConfig)


class LoggingConfig(BaseModel):
    """Structured logging configuration."""

    enabled: bool = Field(default=False, description="Enable structured logging to file")
    level: str = Field(default="info", description="Log level: debug, info, warning, error")
    file: str | None = Field(
        default=None,
        description="Log file path (e.g., 'logs/galangal.jsonl'). If not set, logs only to console.",
    )
    activity_file: str | None = Field(
        default=None,
        description=(
            "Optional activity log file path. Supports {task_name} placeholder for per-task logs."
        ),
    )
    json_format: bool = Field(
        default=True, description="Output JSON format (False for pretty console format)"
    )
    console: bool = Field(default=False, description="Also output to console (stderr)")


class PRConfig(BaseModel):
    """Pull request configuration."""

    codex_review: bool = Field(default=False, description="Add @codex review to PR body")
    base_branch: str = Field(default="main", description="Base branch for PRs")


class TaskTypeSettings(BaseModel):
    """Settings specific to a task type."""

    skip_discovery: bool = Field(
        default=False,
        description="Skip the discovery Q&A phase for this task type",
    )


class ArtifactDependencySpec(BaseModel):
    """Specifies a dependency on an artifact, optionally limited to specific sections.

    When sections is empty, the entire artifact is tracked as a dependency.
    When sections is specified, only those sections (by normalized header name)
    are considered for staleness detection.
    """

    artifact: str = Field(description="Name of the artifact file (e.g., 'SPEC.md')")
    sections: list[str] = Field(
        default_factory=list,
        description="Specific sections to track (empty = entire artifact)",
    )


class StageDependencyConfig(BaseModel):
    """Dependency configuration for a stage.

    Stages can depend on:
    - Other stages (the stage must have completed)
    - Specific artifacts or sections within artifacts
    """

    depends_on_stages: list[str] = Field(
        default_factory=list,
        description="Stages that must complete before this stage (e.g., ['DEV', 'TEST'])",
    )
    depends_on_artifacts: list[ArtifactDependencySpec] = Field(
        default_factory=list,
        description="Artifacts (with optional sections) this stage depends on",
    )


class LineageConfig(BaseModel):
    """Configuration for artifact lineage tracking.

    When enabled, tracks section-level hashes of markdown artifacts to detect
    when upstream changes should invalidate downstream stages.
    """

    enabled: bool = Field(
        default=False,
        description="Enable artifact lineage tracking for staleness detection",
    )
    block_on_staleness: bool = Field(
        default=True,
        description="Force re-run of stale stages (vs just warning)",
    )
    artifact_dependencies: dict[str, list[ArtifactDependencySpec]] = Field(
        default_factory=dict,
        description="Per-artifact dependency configuration (artifact -> [dependencies])",
    )
    stage_dependencies: dict[str, StageDependencyConfig] = Field(
        default_factory=dict,
        description="Per-stage dependency configuration (stage -> config)",
    )


class GitHubLabelMapping(BaseModel):
    """Maps GitHub labels to task types."""

    bug: list[str] = Field(
        default_factory=lambda: ["bug", "bugfix"],
        description="Labels that map to bug_fix task type",
    )
    feature: list[str] = Field(
        default_factory=lambda: ["enhancement", "feature"],
        description="Labels that map to feature task type",
    )
    docs: list[str] = Field(
        default_factory=lambda: ["documentation", "docs"],
        description="Labels that map to docs task type",
    )
    refactor: list[str] = Field(
        default_factory=lambda: ["refactor"],
        description="Labels that map to refactor task type",
    )
    chore: list[str] = Field(
        default_factory=lambda: ["chore", "maintenance"],
        description="Labels that map to chore task type",
    )
    hotfix: list[str] = Field(
        default_factory=lambda: ["hotfix", "critical"],
        description="Labels that map to hotfix task type",
    )


class GitHubConfig(BaseModel):
    """GitHub integration configuration."""

    pickup_label: str = Field(
        default="galangal",
        description="Label that marks issues for galangal to pick up",
    )
    in_progress_label: str = Field(
        default="in-progress",
        description="Label added when galangal starts working on an issue",
    )
    label_colors: dict[str, str] = Field(
        default_factory=lambda: {
            "galangal": "7C3AED",  # Purple
            "in-progress": "FCD34D",  # Yellow
        },
        description="Hex colors for labels (without #)",
    )
    label_mapping: GitHubLabelMapping = Field(
        default_factory=GitHubLabelMapping,
        description="Maps GitHub labels to task types",
    )


class GalangalConfig(BaseModel):
    """Root configuration model."""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    tasks_dir: str = Field(default="galangal-tasks", description="Task storage directory")
    branch_pattern: str = Field(default="task/{task_name}", description="Git branch naming pattern")
    stages: StageConfig = Field(default_factory=StageConfig)
    test_gate: TestGateConfig = Field(
        default_factory=TestGateConfig,
        description="Test gate configuration - mechanical test verification stage",
    )
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    pr: PRConfig = Field(default_factory=PRConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    prompt_context: str = Field(default="", description="Global context added to all prompts")
    stage_context: dict[str, str] = Field(
        default_factory=dict, description="Per-stage prompt context"
    )
    task_type_settings: dict[str, TaskTypeSettings] = Field(
        default_factory=dict,
        description="Per-task-type settings (e.g., skip_discovery for bugfix tasks)",
    )
    artifact_context: ArtifactContextConfig | None = Field(
        default=None,
        description="Per-stage artifact context filtering. If not set, uses default stage logic.",
    )
    lineage: LineageConfig = Field(
        default_factory=LineageConfig,
        description="Artifact lineage tracking for staleness detection",
    )
    hub: HubConfig = Field(
        default_factory=HubConfig,
        description="Hub connection configuration for remote monitoring and control",
    )
