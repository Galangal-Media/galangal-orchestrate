"""
Default configuration values and templates.
"""

DEFAULT_CONFIG_YAML = """\
# Galangal Orchestrate Configuration
# https://github.com/Galangal-Media/galangal-orchestrate

project:
  name: "{project_name}"

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
    artifacts_required:
      - "MIGRATION_REPORT.md"

  # Contract - API contract validation (auto-skip if no API files changed)
  contract:
    skip_if:
      no_files_match:
        - "**/api/**"
        - "**/openapi*"
        - "**/swagger*"
        - "**/*schema*.json"
        - "**/*schema*.yaml"
    artifacts_required:
      - "CONTRACT_REPORT.md"

  # Benchmark - performance benchmarks (auto-skip if no perf-critical files changed)
  benchmark:
    skip_if:
      no_files_match:
        - "**/benchmark/**"
        - "**/perf/**"
        - "**/*benchmark*"
    artifacts_required:
      - "BENCHMARK_REPORT.md"

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
      args: ["--output-format", "stream-json", "--verbose", "--max-turns", "{{max_turns}}", "--permission-mode", "bypassPermissions"]
      max_turns: 200

# =============================================================================
# Pull Request Configuration
# =============================================================================

pr:
  codex_review: false      # Set to true to add @codex review to PR body
  base_branch: main

# =============================================================================
# GitHub Integration
# =============================================================================
# Configure how galangal integrates with GitHub Issues.
# Run 'galangal github setup' to create required labels.

github:
  # Label that marks issues for galangal to pick up
  pickup_label: galangal

  # Label added when galangal starts working on an issue
  in_progress_label: in-progress

  # Colors for labels (hex without #)
  label_colors:
    galangal: "7C3AED"       # Purple
    in-progress: "FCD34D"    # Yellow

  # Map GitHub labels to task types
  # Add your custom labels here
  label_mapping:
    bug:
      - bug
      - bugfix
    feature:
      - enhancement
      - feature
    docs:
      - documentation
      - docs
    refactor:
      - refactor
    chore:
      - chore
      - maintenance
    hotfix:
      - hotfix
      - critical

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


def generate_default_config(project_name: str = "My Project") -> str:
    """Generate a default config.yaml content."""
    return DEFAULT_CONFIG_YAML.format(project_name=project_name)
