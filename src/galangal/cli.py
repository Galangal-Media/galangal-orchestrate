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
    parser = argparse.ArgumentParser(
        description="Galangal Orchestrate - AI-Driven Development Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_build_epilog(),
    )

    # Global --debug flag (before subparsers)
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug logging to logs/galangal_debug.log and logs/galangal.jsonl",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize galangal in current project")
    init_parser.set_defaults(func=_cmd_init)

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


if __name__ == "__main__":
    sys.exit(main())
