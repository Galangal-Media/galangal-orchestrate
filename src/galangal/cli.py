#!/usr/bin/env python3
"""
Galangal Orchestrate - AI-Driven Development Workflow CLI

Usage:
    galangal init                           - Initialize in current project
    galangal start "task description"       - Start new task
    galangal start "desc" --name my-task    - Start with explicit name
    galangal list                           - List all tasks
    galangal switch <task-name>             - Switch active task
    galangal status                         - Show active task status
    galangal resume                         - Continue active task
    galangal pause                          - Pause task for break/shutdown
    galangal reset                          - Delete active task
    galangal complete                       - Move task to done/, create PR
    galangal prompts export                 - Export default prompts for customization

Debug mode:
    galangal --debug <command>              - Enable debug logging to logs/galangal_debug.log
    GALANGAL_DEBUG=1 galangal <command>     - Alternative via environment variable
"""

import argparse
import os
import sys


def _setup_debug_mode() -> None:
    """Enable debug mode by setting environment variable and configuring logging."""
    os.environ["GALANGAL_DEBUG"] = "1"

    from galangal.config.loader import get_project_root

    # Create logs directory in project root (not cwd)
    logs_dir = get_project_root() / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Write initial debug log entry immediately so file is always created
    # Do this BEFORE configure_logging to ensure we have a log even if that fails
    from galangal.core.utils import debug_log, reset_debug_state

    reset_debug_state()  # Clear any cached state
    debug_log("Debug mode enabled", command=" ".join(sys.argv))

    # Also enable structured logging to file
    try:
        from galangal.logging import configure_logging

        configure_logging(
            level="debug",
            log_file=logs_dir / "galangal.jsonl",
            json_format=True,
            console_output=False,  # Don't spam console, just log to file
        )
    except Exception as e:
        debug_log("Failed to configure structured logging", error=str(e))


def _build_epilog() -> str:
    """Build CLI epilog from canonical sources in state.py."""
    from galangal.core.state import TaskType, get_workflow_diagram

    # Build task types section from TaskType enum
    task_lines = []
    for i, tt in enumerate(TaskType, start=1):
        task_lines.append(f"    [{i}] {tt.display_name():10} - {tt.short_description()}")

    task_types_section = "\n".join(task_lines)

    # Build workflow diagram from STAGE_ORDER
    workflow = get_workflow_diagram().replace("→", "->")

    return f"""
Debug mode:
  galangal --debug start "task"   Enable verbose logging to logs/galangal_debug.log
  GALANGAL_DEBUG=1 galangal ...   Alternative via environment variable

Examples:
  galangal init
  galangal start "Add user authentication"
  galangal start "Add auth" --name add-auth-feature
  galangal list
  galangal switch add-auth-feature
  galangal status
  galangal resume
  galangal pause
  galangal skip-to DEV
  galangal skip-to TEST --resume
  galangal complete
  galangal reset
  galangal prompts export

Task Types:
  At task start, you'll select from:
{task_types_section}

Workflow:
  {workflow}

  * = Conditional stages (auto-skipped if condition not met)

Tip: Press Ctrl+C during execution to pause gracefully.
        """


def main() -> int:
    from galangal import __version__

    parser = argparse.ArgumentParser(
        description="Galangal Orchestrate - AI-Driven Development Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_build_epilog(),
    )

    # Global flags (before subparsers)
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"galangal {__version__}",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug logging to logs/galangal_debug.log and logs/galangal.jsonl",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize galangal in current project")
    init_parser.add_argument(
        "--quick",
        "-q",
        action="store_true",
        help="Quick init without interactive wizard (for CI/automation)",
    )
    init_parser.set_defaults(func=_cmd_init)

    # doctor
    doctor_parser = subparsers.add_parser("doctor", help="Verify environment setup")
    doctor_parser.set_defaults(func=_cmd_doctor)

    # start
    start_parser = subparsers.add_parser("start", help="Start new task")
    start_parser.add_argument(
        "description", nargs="*", help="Task description (prompted if not provided)"
    )
    start_parser.add_argument("--name", "-n", help="Task name (auto-generated if not provided)")
    start_parser.add_argument(
        "--type",
        "-t",
        choices=[
            "feature",
            "bugfix",
            "refactor",
            "chore",
            "docs",
            "hotfix",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
        ],
        help="Task type (skip interactive selection)",
    )
    start_parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip the discovery Q&A phase and go straight to spec generation",
    )
    start_parser.add_argument(
        "--issue", "-i", type=int, help="Create task from GitHub issue number"
    )
    start_parser.set_defaults(func=_cmd_start)

    # list
    list_parser = subparsers.add_parser("list", help="List all tasks")
    list_parser.set_defaults(func=_cmd_list)

    # switch
    switch_parser = subparsers.add_parser("switch", help="Switch active task")
    switch_parser.add_argument("task_name", help="Task name to switch to")
    switch_parser.set_defaults(func=_cmd_switch)

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume active task")
    resume_parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip remaining discovery Q&A and go straight to spec generation",
    )
    resume_parser.add_argument(
        "--ignore-staleness",
        action="store_true",
        dest="ignore_staleness",
        help="Skip lineage staleness checks (don't prompt about changed artifacts)",
    )
    resume_parser.set_defaults(func=_cmd_resume)

    # pause
    pause_parser = subparsers.add_parser("pause", help="Pause task for break/shutdown")
    pause_parser.set_defaults(func=_cmd_pause)

    # status
    status_parser = subparsers.add_parser("status", help="Show active task status")
    status_parser.set_defaults(func=_cmd_status)

    # skip-to
    skip_to_parser = subparsers.add_parser(
        "skip-to", help="Jump to a specific stage (for debugging/re-running)"
    )
    skip_to_parser.add_argument("stage", help="Target stage (e.g., DEV, TEST, SECURITY)")
    skip_to_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    skip_to_parser.add_argument(
        "--resume", "-r", action="store_true", help="Resume workflow immediately after jumping"
    )
    skip_to_parser.set_defaults(func=_cmd_skip_to)

    # reset
    reset_parser = subparsers.add_parser("reset", help="Delete active task")
    reset_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    reset_parser.set_defaults(func=_cmd_reset)

    # complete
    complete_parser = subparsers.add_parser(
        "complete", help="Move completed task to done/, create PR"
    )
    complete_parser.add_argument(
        "--force", "-f", action="store_true", help="Continue on commit errors"
    )
    complete_parser.set_defaults(func=_cmd_complete)

    # prompts
    prompts_parser = subparsers.add_parser("prompts", help="Manage prompts")
    prompts_subparsers = prompts_parser.add_subparsers(dest="prompts_command")
    prompts_export = prompts_subparsers.add_parser(
        "export", help="Export default prompts for customization"
    )
    prompts_export.set_defaults(func=_cmd_prompts_export)
    prompts_show = prompts_subparsers.add_parser("show", help="Show effective prompt for a stage")
    prompts_show.add_argument("stage", help="Stage name (e.g., pm, dev, test)")
    prompts_show.set_defaults(func=_cmd_prompts_show)

    # github
    github_parser = subparsers.add_parser("github", help="GitHub integration")
    github_subparsers = github_parser.add_subparsers(dest="github_command")
    github_setup = github_subparsers.add_parser(
        "setup", help="Set up GitHub integration (create labels, verify gh CLI)"
    )
    github_setup.add_argument(
        "--help-install", action="store_true", help="Show detailed gh CLI installation instructions"
    )
    github_setup.set_defaults(func=_cmd_github_setup)
    github_check = github_subparsers.add_parser(
        "check", help="Check GitHub CLI installation and authentication"
    )
    github_check.set_defaults(func=_cmd_github_check)
    github_issues = github_subparsers.add_parser("issues", help="List issues with galangal label")
    github_issues.add_argument(
        "--label", "-l", default="galangal", help="Label to filter by (default: galangal)"
    )
    github_issues.add_argument(
        "--limit", "-n", type=int, default=50, help="Maximum number of issues to list"
    )
    github_issues.set_defaults(func=_cmd_github_issues)
    github_run = github_subparsers.add_parser(
        "run", help="Process all galangal-labeled issues (headless mode)"
    )
    github_run.add_argument(
        "--label", "-l", default="galangal", help="Label to filter by (default: galangal)"
    )
    github_run.add_argument(
        "--dry-run", action="store_true", help="List issues without processing them"
    )
    github_run.set_defaults(func=_cmd_github_run)

    # config
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_edit = config_subparsers.add_parser(
        "edit", help="Launch interactive config editor"
    )
    config_edit.set_defaults(func=_cmd_config_edit)
    config_show = config_subparsers.add_parser("show", help="Show current configuration")
    config_show.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    config_show.set_defaults(func=_cmd_config_show)
    config_schema = config_subparsers.add_parser(
        "schema", help="Export JSON Schema for config.yaml"
    )
    config_schema.set_defaults(func=_cmd_config_schema)
    config_validate = config_subparsers.add_parser(
        "validate", help="Validate current configuration"
    )
    config_validate.set_defaults(func=_cmd_config_validate)

    # mistakes
    mistakes_parser = subparsers.add_parser(
        "mistakes", help="View and manage tracked mistakes"
    )
    mistakes_subparsers = mistakes_parser.add_subparsers(dest="mistakes_command")
    mistakes_list = mistakes_subparsers.add_parser("list", help="List tracked mistakes")
    mistakes_list.add_argument(
        "--limit", "-n", type=int, default=20, help="Maximum number of mistakes to show"
    )
    mistakes_list.add_argument(
        "--stage", "-s", help="Filter by stage (e.g., DEV, TEST)"
    )
    mistakes_list.set_defaults(func=_cmd_mistakes_list)
    mistakes_stats = mistakes_subparsers.add_parser("stats", help="Show mistake statistics")
    mistakes_stats.set_defaults(func=_cmd_mistakes_stats)
    mistakes_search = mistakes_subparsers.add_parser(
        "search", help="Search for similar mistakes"
    )
    mistakes_search.add_argument("query", help="Search query")
    mistakes_search.set_defaults(func=_cmd_mistakes_search)
    mistakes_delete = mistakes_subparsers.add_parser("delete", help="Delete a mistake by ID")
    mistakes_delete.add_argument("id", type=int, help="Mistake ID to delete")
    mistakes_delete.set_defaults(func=_cmd_mistakes_delete)

    # archive
    archive_parser = subparsers.add_parser(
        "archive", help="Archive old completed tasks"
    )
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command")

    # archive (default action - archive tasks)
    archive_run = archive_subparsers.add_parser(
        "run", help="Archive completed tasks (default action)"
    )
    archive_run.add_argument(
        "--before", "-b",
        help="Only archive tasks completed before this duration (e.g., 30d, 2w, 6m)"
    )
    archive_run.add_argument(
        "--compress", "-c", action="store_true",
        help="Compress archived tasks as .tar.gz"
    )
    archive_run.add_argument(
        "--force", "-f", action="store_true",
        help="Skip confirmation"
    )
    archive_run.set_defaults(func=_cmd_archive)

    archive_list = archive_subparsers.add_parser("list", help="List archived tasks")
    archive_list.add_argument(
        "--search", "-s", help="Filter by name or description"
    )
    archive_list.set_defaults(func=_cmd_archive_list)

    archive_restore = archive_subparsers.add_parser(
        "restore", help="Restore an archived task"
    )
    archive_restore.add_argument("task_name", help="Name of task to restore")
    archive_restore.set_defaults(func=_cmd_archive_restore)

    # Set default subcommand for archive (show help if no subcommand)
    archive_parser.set_defaults(func=lambda args: archive_parser.print_help() or 0)

    # hub
    hub_parser = subparsers.add_parser("hub", help="Hub connection management")
    hub_subparsers = hub_parser.add_subparsers(dest="hub_command")
    hub_status = hub_subparsers.add_parser("status", help="Show hub connection status")
    hub_status.set_defaults(func=_cmd_hub_status)
    hub_test = hub_subparsers.add_parser("test", help="Test connection to hub")
    hub_test.set_defaults(func=_cmd_hub_test)
    hub_info = hub_subparsers.add_parser("info", help="Show hub server information")
    hub_info.set_defaults(func=_cmd_hub_info)
    hub_parser.set_defaults(func=lambda args: hub_parser.print_help() or 0)

    args = parser.parse_args()

    # Enable debug mode if requested
    if args.debug:
        _setup_debug_mode()

    result: int = args.func(args)
    return result


# Command wrappers that import lazily to speed up CLI startup
def _cmd_init(args: argparse.Namespace) -> int:
    from galangal.commands.init import cmd_init

    return cmd_init(args)


def _cmd_doctor(args: argparse.Namespace) -> int:
    from galangal.commands.doctor import cmd_doctor

    return cmd_doctor(args)


def _cmd_start(args: argparse.Namespace) -> int:
    from galangal.commands.start import cmd_start

    return cmd_start(args)


def _cmd_list(args: argparse.Namespace) -> int:
    from galangal.commands.list import cmd_list

    return cmd_list(args)


def _cmd_switch(args: argparse.Namespace) -> int:
    from galangal.commands.switch import cmd_switch

    return cmd_switch(args)


def _cmd_resume(args: argparse.Namespace) -> int:
    from galangal.commands.resume import cmd_resume

    return cmd_resume(args)


def _cmd_pause(args: argparse.Namespace) -> int:
    from galangal.commands.pause import cmd_pause

    return cmd_pause(args)


def _cmd_status(args: argparse.Namespace) -> int:
    from galangal.commands.status import cmd_status

    return cmd_status(args)


def _cmd_skip_to(args: argparse.Namespace) -> int:
    from galangal.commands.skip import cmd_skip_to

    return cmd_skip_to(args)


def _cmd_reset(args: argparse.Namespace) -> int:
    from galangal.commands.reset import cmd_reset

    return cmd_reset(args)


def _cmd_complete(args: argparse.Namespace) -> int:
    from galangal.commands.complete import cmd_complete

    return cmd_complete(args)


def _cmd_prompts_export(args: argparse.Namespace) -> int:
    from galangal.commands.prompts import cmd_prompts_export

    return cmd_prompts_export(args)


def _cmd_prompts_show(args: argparse.Namespace) -> int:
    from galangal.commands.prompts import cmd_prompts_show

    return cmd_prompts_show(args)


def _cmd_github_setup(args: argparse.Namespace) -> int:
    from galangal.commands.github import cmd_github_setup

    return cmd_github_setup(args)


def _cmd_github_check(args: argparse.Namespace) -> int:
    from galangal.commands.github import cmd_github_check

    return cmd_github_check(args)


def _cmd_github_issues(args: argparse.Namespace) -> int:
    from galangal.commands.github import cmd_github_issues

    return cmd_github_issues(args)


def _cmd_github_run(args: argparse.Namespace) -> int:
    from galangal.commands.github import cmd_github_run

    return cmd_github_run(args)


def _cmd_config_edit(args: argparse.Namespace) -> int:
    from galangal.commands.config import cmd_config_edit

    return cmd_config_edit(args)


def _cmd_config_show(args: argparse.Namespace) -> int:
    from galangal.commands.config import cmd_config_show

    return cmd_config_show(args)


def _cmd_config_schema(args: argparse.Namespace) -> int:
    from galangal.commands.config import cmd_config_schema

    return cmd_config_schema(args)


def _cmd_config_validate(args: argparse.Namespace) -> int:
    from galangal.commands.config import cmd_config_validate

    return cmd_config_validate(args)


def _cmd_mistakes_list(args: argparse.Namespace) -> int:
    from galangal.commands.mistakes import cmd_mistakes_list

    return cmd_mistakes_list(args)


def _cmd_mistakes_stats(args: argparse.Namespace) -> int:
    from galangal.commands.mistakes import cmd_mistakes_stats

    return cmd_mistakes_stats(args)


def _cmd_mistakes_search(args: argparse.Namespace) -> int:
    from galangal.commands.mistakes import cmd_mistakes_search

    return cmd_mistakes_search(args)


def _cmd_mistakes_delete(args: argparse.Namespace) -> int:
    from galangal.commands.mistakes import cmd_mistakes_delete

    return cmd_mistakes_delete(args)


def _cmd_archive(args: argparse.Namespace) -> int:
    from galangal.commands.archive import cmd_archive

    return cmd_archive(args)


def _cmd_archive_list(args: argparse.Namespace) -> int:
    from galangal.commands.archive import cmd_archive_list

    return cmd_archive_list(args)


def _cmd_archive_restore(args: argparse.Namespace) -> int:
    from galangal.commands.archive import cmd_archive_restore

    return cmd_archive_restore(args)


def _cmd_hub_status(args: argparse.Namespace) -> int:
    from galangal.commands.hub import cmd_hub_status

    return cmd_hub_status(args)


def _cmd_hub_test(args: argparse.Namespace) -> int:
    from galangal.commands.hub import cmd_hub_test

    return cmd_hub_test(args)


def _cmd_hub_info(args: argparse.Namespace) -> int:
    from galangal.commands.hub import cmd_hub_info

    return cmd_hub_info(args)


if __name__ == "__main__":
    sys.exit(main())
