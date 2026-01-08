"""
Configuration schema using Pydantic models.
"""


from pydantic import BaseModel, Field


class StackConfig(BaseModel):
    """Configuration for a technology stack."""

    language: str = Field(description="Programming language (python, typescript, php, etc.)")
    framework: str | None = Field(default=None, description="Framework (fastapi, vite, symfony)")
    root: str | None = Field(default=None, description="Subdirectory for this stack")


class ProjectConfig(BaseModel):
    """Project-level configuration."""

    name: str = Field(default="My Project", description="Project name")
    stacks: list[StackConfig] = Field(default_factory=list, description="Technology stacks")
    approver_name: str | None = Field(default=None, description="Default approver name for plan approvals")


class StageConfig(BaseModel):
    """Stage execution configuration."""

    skip: list[str] = Field(default_factory=list, description="Stages to always skip")
    timeout: int = Field(default=14400, description="Stage timeout in seconds (default: 4 hours)")
    max_retries: int = Field(default=5, description="Max retries per stage")


class PreflightCheck(BaseModel):
    """A single preflight check."""

    name: str = Field(description="Check name for display")
    command: str | None = Field(default=None, description="Command to run")
    path_exists: str | None = Field(default=None, description="Path that must exist")
    expect_empty: bool = Field(default=False, description="Pass if output is empty")
    warn_only: bool = Field(default=False, description="Warn but don't fail the stage")


class ValidationCommand(BaseModel):
    """A validation command configuration."""

    name: str = Field(description="Command name for display")
    command: str = Field(description="Shell command to run")
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
    commands: list[ValidationCommand] = Field(
        default_factory=list, description="Commands to run"
    )
    checks: list[PreflightCheck] = Field(
        default_factory=list, description="Preflight checks (for preflight stage)"
    )
    pass_marker: str | None = Field(
        default=None, description="Text marker indicating pass (for AI stages)"
    )
    fail_marker: str | None = Field(
        default=None, description="Text marker indicating failure (for AI stages)"
    )
    artifact: str | None = Field(
        default=None, description="Artifact file to check for markers"
    )
    artifacts_required: list[str] = Field(
        default_factory=list, description="Required artifact files"
    )


class ValidationConfig(BaseModel):
    """All stage validations."""

    preflight: StageValidation = Field(default_factory=StageValidation)
    migration: StageValidation = Field(default_factory=StageValidation)
    test: StageValidation = Field(default_factory=StageValidation)
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


class AIConfig(BaseModel):
    """AI backend configuration."""

    default: str = Field(default="claude", description="Default backend")
    backends: dict[str, AIBackendConfig] = Field(
        default_factory=lambda: {
            "claude": AIBackendConfig(
                command="claude",
                args=["-p", "{prompt}", "--output-format", "stream-json", "--verbose"],
                max_turns=200,
            )
        }
    )
    stage_backends: dict[str, str] = Field(
        default_factory=dict, description="Per-stage backend overrides"
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


class LoggingConfig(BaseModel):
    """Structured logging configuration."""

    enabled: bool = Field(default=False, description="Enable structured logging to file")
    level: str = Field(default="info", description="Log level: debug, info, warning, error")
    file: str | None = Field(
        default=None,
        description="Log file path (e.g., 'logs/galangal.jsonl'). If not set, logs only to console.",
    )
    json_format: bool = Field(
        default=True, description="Output JSON format (False for pretty console format)"
    )
    console: bool = Field(default=False, description="Also output to console (stderr)")


class PRConfig(BaseModel):
    """Pull request configuration."""

    codex_review: bool = Field(
        default=False, description="Add @codex review to PR body"
    )
    base_branch: str = Field(default="main", description="Base branch for PRs")


class GalangalConfig(BaseModel):
    """Root configuration model."""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    tasks_dir: str = Field(default="galangal-tasks", description="Task storage directory")
    branch_pattern: str = Field(
        default="task/{task_name}", description="Git branch naming pattern"
    )
    stages: StageConfig = Field(default_factory=StageConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    pr: PRConfig = Field(default_factory=PRConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    prompt_context: str = Field(
        default="", description="Global context added to all prompts"
    )
    stage_context: dict[str, str] = Field(
        default_factory=dict, description="Per-stage prompt context"
    )
