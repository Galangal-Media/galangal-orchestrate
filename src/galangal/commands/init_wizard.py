"""
Interactive setup wizard for galangal init.

Guides users through configuration with questions, building a config.yaml
that matches their project setup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rich.prompt import Confirm, Prompt
from rich.table import Table

from galangal.ui.console import console, print_info, print_success, print_warning


@dataclass
class WizardConfig:
    """Configuration collected during wizard setup."""

    # Project basics
    project_name: str = "My Project"
    approver_name: str = ""

    # Task storage
    tasks_dir: str = "galangal-tasks"
    branch_pattern: str = "task/{task_name}"

    # Stage configuration
    skip_stages: list[str] = field(default_factory=lambda: ["BENCHMARK"])
    timeout: int = 14400
    max_retries: int = 5

    # Test gate
    test_gate_enabled: bool = False
    test_gate_tests: list[dict[str, Any]] = field(default_factory=list)
    test_gate_fail_fast: bool = True

    # AI configuration
    ai_backend: str = "claude"
    codex_review: bool = False
    base_branch: str = "main"

    # Docs configuration
    changelog_dir: str = "docs/changelog"
    update_changelog: bool = True

    # Preflight checks
    preflight_git_clean: bool = True
    preflight_git_clean_warn_only: bool = True

    # Custom prompt context
    prompt_context: str = ""

    # Artifact context filtering
    artifact_context_enabled: bool = False

    def to_yaml(self) -> str:
        """Convert wizard config to YAML string."""
        return generate_config_yaml(self)


def run_wizard(
    project_root: Path,
    existing_config: dict[str, Any] | None = None,
) -> WizardConfig:
    """
    Run the interactive setup wizard.

    Args:
        project_root: Path to the project root directory.
        existing_config: Existing config dict if updating, None for new setup.

    Returns:
        WizardConfig with all collected settings.
    """
    config = WizardConfig()
    is_update = existing_config is not None

    if is_update:
        console.print("\n[bold cyan]Configuration Update Wizard[/bold cyan]")
        console.print("[dim]We'll check for missing sections and help you configure them.[/dim]\n")
        # Pre-populate from existing config
        _load_existing_config(config, existing_config)
    else:
        console.print("\n[bold cyan]Interactive Setup Wizard[/bold cyan]")
        console.print("[dim]Answer a few questions to configure galangal for your project.[/dim]")
        console.print("[dim]Press Enter to accept defaults shown in brackets.[/dim]\n")

    # Step 1: Project basics
    _step_project_basics(config, project_root, is_update, existing_config)

    # Step 2: AI backend
    _step_ai_backend(config, is_update, existing_config)

    # Step 3: Test gate
    _step_test_gate(config, is_update, existing_config)

    # Step 4: Preflight checks
    _step_preflight(config, is_update, existing_config)

    # Step 5: Stages to skip
    _step_stages(config, is_update, existing_config)

    # Step 6: Documentation
    _step_docs(config, is_update, existing_config)

    # Step 7: Custom prompt context
    _step_prompt_context(config, is_update, existing_config)

    # Step 8: Artifact context filtering
    _step_artifact_context(config, is_update, existing_config)

    # Summary
    _show_summary(config)

    return config


def _section_exists(existing: dict[str, Any] | None, *keys: str) -> bool:
    """Check if a section exists in existing config."""
    if existing is None:
        return False
    current = existing
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def _section_header(title: str) -> None:
    """Print a section header."""
    console.print(f"\n[bold yellow]{'─' * 60}[/bold yellow]")
    console.print(f"[bold yellow]{title}[/bold yellow]")
    console.print(f"[bold yellow]{'─' * 60}[/bold yellow]\n")


def _step_project_basics(
    config: WizardConfig,
    project_root: Path,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 1: Project basics."""
    if is_update and _section_exists(existing, "project", "name"):
        if not Confirm.ask("Update project settings?", default=False):
            return

    _section_header("1. Project Basics")

    default_name = config.project_name if config.project_name != "My Project" else project_root.name
    config.project_name = Prompt.ask("Project name", default=default_name)

    config.approver_name = Prompt.ask(
        "Default approver name (for plan/design signoffs)",
        default=config.approver_name or "",
    )

    config.base_branch = Prompt.ask(
        "Git base branch for PRs",
        default=config.base_branch,
    )

    print_success(f"Project: {config.project_name}")


def _step_ai_backend(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 2: AI backend configuration."""
    if is_update and _section_exists(existing, "ai", "default"):
        if not Confirm.ask("Update AI backend settings?", default=False):
            return

    _section_header("2. AI Backend")

    console.print("[dim]Galangal uses Claude Code CLI by default.[/dim]")

    config.codex_review = Confirm.ask(
        "Use Codex for independent code review? (adds @codex to PRs)",
        default=config.codex_review,
    )

    print_success(f"AI backend: {config.ai_backend}" + (" + Codex review" if config.codex_review else ""))


def _step_test_gate(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 3: Test gate configuration."""
    if is_update and _section_exists(existing, "test_gate", "enabled"):
        if not Confirm.ask("Update test gate settings?", default=False):
            return

    _section_header("3. Test Gate")

    console.print("[dim]The Test Gate runs configured test suites as a quality gate.[/dim]")
    console.print("[dim]Tests must pass before QA stage can begin.[/dim]\n")

    config.test_gate_enabled = Confirm.ask(
        "Enable Test Gate stage?",
        default=config.test_gate_enabled,
    )

    if not config.test_gate_enabled:
        print_info("Test Gate disabled - tests will run in QA stage instead")
        return

    # Collect test commands
    config.test_gate_tests = []
    console.print("\n[dim]Add test suites to run. Leave name empty when done.[/dim]\n")

    while True:
        test_name = Prompt.ask("Test suite name (empty to finish)", default="")
        if not test_name:
            break

        test_command = Prompt.ask(f"Command to run '{test_name}'")
        if not test_command:
            print_warning("Command cannot be empty, skipping this test")
            continue

        timeout_str = Prompt.ask("Timeout in seconds", default="300")
        try:
            timeout = int(timeout_str)
        except ValueError:
            timeout = 300

        config.test_gate_tests.append({
            "name": test_name,
            "command": test_command,
            "timeout": timeout,
        })
        print_success(f"Added: {test_name}")

    if config.test_gate_tests:
        config.test_gate_fail_fast = Confirm.ask(
            "Stop on first test failure? (fail_fast)",
            default=config.test_gate_fail_fast,
        )
        print_success(f"Test Gate: {len(config.test_gate_tests)} test suite(s) configured")
    else:
        config.test_gate_enabled = False
        print_info("No tests added - Test Gate disabled")


def _step_preflight(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 4: Preflight checks."""
    if is_update and _section_exists(existing, "validation", "preflight"):
        if not Confirm.ask("Update preflight check settings?", default=False):
            return

    _section_header("4. Preflight Checks")

    console.print("[dim]Preflight checks run before DEV stage to verify environment.[/dim]\n")

    config.preflight_git_clean = Confirm.ask(
        "Check for clean git working tree?",
        default=config.preflight_git_clean,
    )

    if config.preflight_git_clean:
        config.preflight_git_clean_warn_only = Confirm.ask(
            "Warn only (don't block) if working tree has changes?",
            default=config.preflight_git_clean_warn_only,
        )

    print_success("Preflight checks configured")


def _step_stages(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 5: Stages to skip."""
    if is_update and _section_exists(existing, "stages", "skip"):
        if not Confirm.ask("Update stage skip settings?", default=False):
            return

    _section_header("5. Stages to Skip")

    console.print("[dim]Some stages are optional. Skip stages that don't apply to your project.[/dim]\n")

    optional_stages = [
        ("BENCHMARK", "Performance benchmarking", "BENCHMARK" in config.skip_stages),
        ("CONTRACT", "API contract testing (OpenAPI)", "CONTRACT" in config.skip_stages),
        ("MIGRATION", "Database migration checks", "MIGRATION" in config.skip_stages),
        ("SECURITY", "Security review", "SECURITY" in config.skip_stages),
    ]

    config.skip_stages = []
    for stage, desc, default_skip in optional_stages:
        skip = Confirm.ask(f"Skip {stage} stage? ({desc})", default=default_skip)
        if skip:
            config.skip_stages.append(stage)

    if config.skip_stages:
        print_success(f"Skipping: {', '.join(config.skip_stages)}")
    else:
        print_success("All stages enabled")


def _step_docs(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 6: Documentation settings."""
    if is_update and _section_exists(existing, "docs"):
        if not Confirm.ask("Update documentation settings?", default=False):
            return

    _section_header("6. Documentation")

    console.print("[dim]Configure where documentation artifacts are stored.[/dim]\n")

    config.update_changelog = Confirm.ask(
        "Update changelog in DOCS stage?",
        default=config.update_changelog,
    )

    if config.update_changelog:
        config.changelog_dir = Prompt.ask(
            "Changelog directory",
            default=config.changelog_dir,
        )

    print_success("Documentation settings configured")


def _step_prompt_context(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 7: Custom prompt context."""
    if is_update and _section_exists(existing, "prompt_context"):
        if existing.get("prompt_context", "").strip():
            if not Confirm.ask("Update custom prompt context?", default=False):
                return

    _section_header("7. Custom Instructions")

    console.print("[dim]Add project-specific instructions for the AI.[/dim]")
    console.print("[dim]Examples: coding standards, patterns to follow, tech stack details.[/dim]\n")

    add_context = Confirm.ask(
        "Add custom instructions for AI prompts?",
        default=bool(config.prompt_context),
    )

    if add_context:
        console.print("\n[dim]Enter your instructions (single line, or edit config.yaml later):[/dim]")
        config.prompt_context = Prompt.ask("Instructions", default=config.prompt_context or "")
    else:
        config.prompt_context = ""

    print_success("Custom instructions configured")


def _step_artifact_context(
    config: WizardConfig,
    is_update: bool,
    existing: dict[str, Any] | None,
) -> None:
    """Step 8: Artifact context filtering."""
    if is_update and _section_exists(existing, "artifact_context"):
        if not Confirm.ask("Update artifact context filtering?", default=False):
            return

    _section_header("8. Artifact Context Filtering")

    console.print("[dim]Control which artifacts are included in prompts for each stage.[/dim]")
    console.print("[dim]This can reduce token usage by 30-50% on later stages (REVIEW, DOCS, etc.).[/dim]\n")

    config.artifact_context_enabled = Confirm.ask(
        "Enable artifact context filtering? (recommended for cost optimization)",
        default=config.artifact_context_enabled,
    )

    if config.artifact_context_enabled:
        print_success("Artifact filtering enabled with recommended defaults")
        console.print("[dim]Edit .galangal/config.yaml to customize per-stage filtering.[/dim]")
    else:
        print_info("Artifact filtering disabled - all relevant artifacts will be included")


def _show_summary(config: WizardConfig) -> None:
    """Show configuration summary."""
    console.print("\n")
    console.print("[bold green]Configuration Summary[/bold green]")
    console.print("─" * 40)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Project", config.project_name)
    if config.approver_name:
        table.add_row("Approver", config.approver_name)
    table.add_row("Base branch", config.base_branch)
    table.add_row("AI backend", config.ai_backend + (" + Codex review" if config.codex_review else ""))

    if config.test_gate_enabled:
        table.add_row("Test Gate", f"{len(config.test_gate_tests)} test(s)")
    else:
        table.add_row("Test Gate", "Disabled")

    if config.skip_stages:
        table.add_row("Skipped stages", ", ".join(config.skip_stages))

    table.add_row(
        "Artifact filtering",
        "Enabled (recommended)" if config.artifact_context_enabled else "Disabled",
    )

    console.print(table)
    console.print()


def _load_existing_config(config: WizardConfig, existing: dict[str, Any]) -> None:
    """Load existing config values into WizardConfig."""
    # Project
    if "project" in existing:
        config.project_name = existing["project"].get("name", config.project_name)
        config.approver_name = existing["project"].get("approver_name", "")

    # Tasks
    config.tasks_dir = existing.get("tasks_dir", config.tasks_dir)
    config.branch_pattern = existing.get("branch_pattern", config.branch_pattern)

    # Stages
    if "stages" in existing:
        config.skip_stages = existing["stages"].get("skip", config.skip_stages)
        config.timeout = existing["stages"].get("timeout", config.timeout)
        config.max_retries = existing["stages"].get("max_retries", config.max_retries)

    # Test gate
    if "test_gate" in existing:
        config.test_gate_enabled = existing["test_gate"].get("enabled", False)
        config.test_gate_tests = existing["test_gate"].get("tests", [])
        config.test_gate_fail_fast = existing["test_gate"].get("fail_fast", True)

    # AI
    if "ai" in existing:
        config.ai_backend = existing["ai"].get("default", "claude")

    # PR
    if "pr" in existing:
        config.codex_review = existing["pr"].get("codex_review", False)
        config.base_branch = existing["pr"].get("base_branch", "main")

    # Docs
    if "docs" in existing:
        config.changelog_dir = existing["docs"].get("changelog_dir", config.changelog_dir)
        config.update_changelog = existing["docs"].get("update_changelog", True)

    # Preflight
    if "validation" in existing and "preflight" in existing["validation"]:
        preflight = existing["validation"]["preflight"]
        checks = preflight.get("checks", [])
        for check in checks:
            if check.get("name") == "Git clean":
                config.preflight_git_clean = True
                config.preflight_git_clean_warn_only = check.get("warn_only", True)
                break

    # Prompt context
    config.prompt_context = existing.get("prompt_context", "")
    if isinstance(config.prompt_context, str):
        # Strip default template text
        if "Add your project-specific patterns" in config.prompt_context:
            config.prompt_context = ""

    # Artifact context
    config.artifact_context_enabled = existing.get("artifact_context") is not None


def generate_config_yaml(config: WizardConfig) -> str:
    """Generate YAML config from WizardConfig."""
    # Build the config dict
    cfg: dict[str, Any] = {}

    # Project
    cfg["project"] = {"name": config.project_name}
    if config.approver_name:
        cfg["project"]["approver_name"] = config.approver_name

    # Task storage
    cfg["tasks_dir"] = config.tasks_dir
    cfg["branch_pattern"] = config.branch_pattern

    # Stages
    cfg["stages"] = {
        "skip": config.skip_stages,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }

    # Test gate
    cfg["test_gate"] = {
        "enabled": config.test_gate_enabled,
        "fail_fast": config.test_gate_fail_fast,
        "tests": config.test_gate_tests,
    }

    # Validation
    cfg["validation"] = {
        "preflight": {
            "checks": [],
        },
        "migration": {
            "skip_if": {
                "no_files_match": [
                    "**/migrations/**",
                    "**/migrate/**",
                    "**/alembic/**",
                    "**/*migration*",
                    "**/schema/**",
                    "**/db/migrate/**",
                ],
            },
            "artifacts_required": ["MIGRATION_REPORT.md"],
        },
        "contract": {
            "skip_if": {
                "no_files_match": [
                    "**/api/**",
                    "**/openapi*",
                    "**/swagger*",
                    "**/*schema*.json",
                    "**/*schema*.yaml",
                ],
            },
            "artifacts_required": ["CONTRACT_REPORT.md"],
        },
        "benchmark": {
            "skip_if": {
                "no_files_match": [
                    "**/benchmark/**",
                    "**/perf/**",
                    "**/*benchmark*",
                ],
            },
            "artifacts_required": ["BENCHMARK_REPORT.md"],
        },
        "qa": {
            "timeout": 300,
            "commands": [
                {
                    "name": "Tests",
                    "command": "echo 'Configure your test command in .galangal/config.yaml'",
                },
            ],
        },
        "review": {
            "pass_marker": "APPROVE",
            "fail_marker": "REQUEST_CHANGES",
            "artifact": "REVIEW_NOTES.md",
        },
    }

    # Add preflight git check if enabled
    if config.preflight_git_clean:
        cfg["validation"]["preflight"]["checks"].append({
            "name": "Git clean",
            "command": "git status --porcelain",
            "expect_empty": True,
            "warn_only": config.preflight_git_clean_warn_only,
        })

    # AI
    cfg["ai"] = {
        "default": config.ai_backend,
        "backends": {
            "claude": {
                "command": "claude",
                "args": [
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--max-turns",
                    "{max_turns}",
                    "--permission-mode",
                    "bypassPermissions",
                ],
                "max_turns": 200,
            },
        },
    }

    # PR
    cfg["pr"] = {
        "codex_review": config.codex_review,
        "base_branch": config.base_branch,
    }

    # GitHub
    cfg["github"] = {
        "pickup_label": "galangal",
        "in_progress_label": "in-progress",
        "label_colors": {
            "galangal": "7C3AED",
            "in-progress": "FCD34D",
        },
        "label_mapping": {
            "bug": ["bug", "bugfix"],
            "feature": ["enhancement", "feature"],
            "docs": ["documentation", "docs"],
            "refactor": ["refactor"],
            "chore": ["chore", "maintenance"],
            "hotfix": ["hotfix", "critical"],
        },
    }

    # Docs
    cfg["docs"] = {
        "changelog_dir": config.changelog_dir,
        "update_changelog": config.update_changelog,
    }

    # Prompt context
    if config.prompt_context:
        cfg["prompt_context"] = config.prompt_context
    else:
        cfg["prompt_context"] = f"## Project: {config.project_name}\n\nAdd your project-specific patterns, coding standards, and instructions here.\n"

    # Stage context (empty defaults)
    cfg["stage_context"] = {
        "DEV": "# Add DEV-specific context here\n",
        "TEST": "# Add TEST-specific context here\n",
    }

    # Artifact context filtering (if enabled)
    if config.artifact_context_enabled:
        cfg["artifact_context"] = {
            "review": {
                "required": ["SPEC.md", "DEVELOPMENT.md"],
                "include": ["DESIGN.md", "QA_REPORT.md", "SECURITY_CHECKLIST.md"],
                "exclude": ["PREFLIGHT.md", "TEST_PLAN.md", "TEST_GATE_RESULTS.md"],
            },
            "security": {
                "required": ["SPEC.md", "DEVELOPMENT.md"],
                "include": ["DESIGN.md"],
                "exclude": ["TEST_SUMMARY.md", "QA_REPORT.md"],
            },
            "docs": {
                "required": ["SPEC.md", "DEVELOPMENT.md"],
                "include": ["DESIGN.md"],
                "exclude": ["TEST_PLAN.md", "QA_REPORT.md", "SECURITY_CHECKLIST.md"],
            },
            "summary": {
                "required": ["SPEC.md"],
                "include": ["QA_REPORT.md", "SECURITY_CHECKLIST.md", "REVIEW_NOTES.md"],
                "exclude": ["DEVELOPMENT.md", "TEST_PLAN.md", "TEST_SUMMARY.md"],
            },
        }

    # Generate YAML with comments
    yaml_str = _generate_yaml_with_comments(cfg, config)

    return yaml_str


def _generate_yaml_with_comments(cfg: dict[str, Any], config: WizardConfig) -> str:
    """Generate YAML with helpful comments."""
    lines = [
        "# Galangal Orchestrate Configuration",
        "# https://github.com/Galangal-Media/galangal-orchestrate",
        "",
    ]

    # Project
    lines.append("project:")
    lines.append(f'  name: "{cfg["project"]["name"]}"')
    if cfg["project"].get("approver_name"):
        lines.append(f'  approver_name: "{cfg["project"]["approver_name"]}"')
    lines.append("")

    # Task storage
    lines.append("# Task storage location")
    lines.append(f'tasks_dir: {cfg["tasks_dir"]}')
    lines.append("")
    lines.append("# Git branch naming pattern")
    lines.append(f'branch_pattern: "{cfg["branch_pattern"]}"')
    lines.append("")

    # Stages
    lines.append("# " + "=" * 77)
    lines.append("# Stage Configuration")
    lines.append("# " + "=" * 77)
    lines.append("")
    lines.append("stages:")
    lines.append("  # Stages to always skip for this project")
    lines.append("  skip:")
    for stage in cfg["stages"]["skip"]:
        lines.append(f"    - {stage}")
    if not cfg["stages"]["skip"]:
        lines.append("    # - BENCHMARK")
        lines.append("    # - CONTRACT")
    lines.append("")
    lines.append(f'  timeout: {cfg["stages"]["timeout"]}')
    lines.append(f'  max_retries: {cfg["stages"]["max_retries"]}')
    lines.append("")

    # Test gate
    lines.append("# " + "=" * 77)
    lines.append("# Test Gate Configuration")
    lines.append("# Mechanical test verification stage (no AI) - runs after TEST, before QA")
    lines.append("# " + "=" * 77)
    lines.append("")
    lines.append("test_gate:")
    lines.append(f'  enabled: {str(cfg["test_gate"]["enabled"]).lower()}')
    lines.append(f'  fail_fast: {str(cfg["test_gate"]["fail_fast"]).lower()}')
    lines.append("  tests:")
    if cfg["test_gate"]["tests"]:
        for test in cfg["test_gate"]["tests"]:
            lines.append(f'    - name: "{test["name"]}"')
            lines.append(f'      command: "{test["command"]}"')
            lines.append(f'      timeout: {test["timeout"]}')
    else:
        lines.append("    # - name: \"unit tests\"")
        lines.append("    #   command: \"npm test\"")
        lines.append("    #   timeout: 300")
    lines.append("")

    # Validation - use yaml.dump for complex nested structures
    lines.append("# " + "=" * 77)
    lines.append("# Validation Commands")
    lines.append("# " + "=" * 77)
    lines.append("")
    validation_yaml = yaml.dump({"validation": cfg["validation"]}, default_flow_style=False, sort_keys=False)
    lines.append(validation_yaml.strip())
    lines.append("")

    # AI
    lines.append("# " + "=" * 77)
    lines.append("# AI Backend Configuration")
    lines.append("# " + "=" * 77)
    lines.append("")
    ai_yaml = yaml.dump({"ai": cfg["ai"]}, default_flow_style=False, sort_keys=False)
    lines.append(ai_yaml.strip())
    lines.append("")

    # PR
    lines.append("# " + "=" * 77)
    lines.append("# Pull Request Configuration")
    lines.append("# " + "=" * 77)
    lines.append("")
    pr_yaml = yaml.dump({"pr": cfg["pr"]}, default_flow_style=False, sort_keys=False)
    lines.append(pr_yaml.strip())
    lines.append("")

    # GitHub
    lines.append("# " + "=" * 77)
    lines.append("# GitHub Integration")
    lines.append("# " + "=" * 77)
    lines.append("")
    github_yaml = yaml.dump({"github": cfg["github"]}, default_flow_style=False, sort_keys=False)
    lines.append(github_yaml.strip())
    lines.append("")

    # Docs
    lines.append("# " + "=" * 77)
    lines.append("# Documentation Configuration")
    lines.append("# " + "=" * 77)
    lines.append("")
    docs_yaml = yaml.dump({"docs": cfg["docs"]}, default_flow_style=False, sort_keys=False)
    lines.append(docs_yaml.strip())
    lines.append("")

    # Prompt context
    lines.append("# " + "=" * 77)
    lines.append("# Prompt Context")
    lines.append("# " + "=" * 77)
    lines.append("# Add project-specific patterns and instructions here.")
    lines.append("")
    prompt_yaml = yaml.dump({"prompt_context": cfg["prompt_context"]}, default_flow_style=False, sort_keys=False)
    lines.append(prompt_yaml.strip())
    lines.append("")

    # Stage context
    lines.append("# Per-stage prompt additions")
    stage_yaml = yaml.dump({"stage_context": cfg["stage_context"]}, default_flow_style=False, sort_keys=False)
    lines.append(stage_yaml.strip())
    lines.append("")

    # Artifact context filtering
    if "artifact_context" in cfg:
        lines.append("# " + "=" * 77)
        lines.append("# Artifact Context Filtering")
        lines.append("# Control which artifacts are included in prompts per stage (reduces token usage)")
        lines.append("# " + "=" * 77)
        lines.append("")
        artifact_yaml = yaml.dump(
            {"artifact_context": cfg["artifact_context"]},
            default_flow_style=False,
            sort_keys=False,
        )
        lines.append(artifact_yaml.strip())
        lines.append("")

    return "\n".join(lines)


def check_missing_sections(existing_config: dict[str, Any]) -> list[str]:
    """
    Check which sections are missing from an existing config.

    Returns list of section names that should be configured.
    """
    missing = []

    # Sections to check - newer features should be listed with descriptive names
    required_sections = [
        ("project", "Project settings"),
        ("stages", "Stage configuration"),
        ("test_gate", "Test Gate"),  # New in v0.13
        ("validation", "Validation commands"),
        ("ai", "AI backend"),
        ("pr", "Pull request settings"),
        ("github", "GitHub integration"),
    ]

    for section_key, section_name in required_sections:
        if section_key not in existing_config:
            missing.append(section_name)

    return missing
