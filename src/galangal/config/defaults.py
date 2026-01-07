"""
Default configuration values and templates.
"""

DEFAULT_CONFIG_YAML = """\
# Galangal Orchestrate Configuration
# https://github.com/Galangal-Media/galangal-orchestrate

project:
  name: "{project_name}"

  # Technology stacks in this project
  stacks:
{stacks_yaml}

# Task storage location
tasks_dir: galangal-tasks

# Git branch naming pattern
branch_pattern: "task/{{task_name}}"

# =============================================================================
# Stage Configuration
# =============================================================================

stages:
  # Stages to always skip for this project
  skip:
    - BENCHMARK        # Enable if you have performance requirements
    # - CONTRACT       # Enable if you have OpenAPI contract testing
    # - MIGRATION      # Uncomment to always skip (auto-skips if no migration files)

  # Stage timeout in seconds (default: 4 hours)
  timeout: 14400

  # Max retries per stage
  max_retries: 5

# =============================================================================
# Validation Commands
# =============================================================================
# Configure how each stage validates its outputs.
# Use {{task_dir}} placeholder for the task artifacts directory.

validation:
  # Preflight - environment checks (runs directly, no AI)
  preflight:
    checks:
      - name: "Git clean"
        command: "git status --porcelain"
        expect_empty: true
        warn_only: true       # Report but don't fail if working tree has changes

  # Migration - auto-skip if no migration files changed
  migration:
    skip_if:
      no_files_match:
        - "**/migrations/**"
        - "**/migrate/**"
        - "**/alembic/**"
        - "**/*migration*"
        - "**/schema/**"
        - "**/db/migrate/**"

  # QA - quality checks
  qa:
    # Default timeout per command (seconds)
    timeout: 300
    commands:
      - name: "Tests"
        command: "echo 'Configure your test command in .galangal/config.yaml'"
        # timeout: 3600

  # Review - code review (AI-driven)
  review:
    pass_marker: "APPROVE"
    fail_marker: "REQUEST_CHANGES"
    artifact: "REVIEW_NOTES.md"

# =============================================================================
# AI Backend Configuration
# =============================================================================

ai:
  default: claude

  backends:
    claude:
      command: "claude"
      args: ["-p", "{{prompt}}", "--output-format", "stream-json", "--verbose"]
      max_turns: 200

# =============================================================================
# Pull Request Configuration
# =============================================================================

pr:
  codex_review: false      # Set to true to add @codex review to PR body
  base_branch: main

# =============================================================================
# Prompt Context
# =============================================================================
# Add project-specific patterns and instructions here.
# This context is added to ALL stage prompts.

prompt_context: |
  ## Project: {project_name}

  Add your project-specific patterns, coding standards,
  and instructions here.

# Per-stage prompt additions
stage_context:
  DEV: |
    # Add DEV-specific context here
  TEST: |
    # Add TEST-specific context here
"""


def generate_default_config(
    project_name: str = "My Project",
    stacks: list[dict[str, str]] | None = None,
) -> str:
    """Generate a default config.yaml content."""
    if stacks is None:
        stacks = [{"language": "python", "framework": None, "root": None}]

    # Build stacks YAML
    stacks_lines = []
    for stack in stacks:
        stacks_lines.append(f"    - language: {stack['language']}")
        if stack.get("framework"):
            stacks_lines.append(f"      framework: {stack['framework']}")
        if stack.get("root"):
            stacks_lines.append(f"      root: {stack['root']}")

    stacks_yaml = "\n".join(stacks_lines) if stacks_lines else "    []"

    return DEFAULT_CONFIG_YAML.format(
        project_name=project_name,
        stacks_yaml=stacks_yaml,
    )
