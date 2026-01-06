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
    galangal approve                        - Record plan approval
    galangal approve-design                 - Record design review
    galangal skip-design                    - Skip design for trivial tasks
    galangal skip-security                  - Skip security for non-code changes
    galangal reset                          - Delete active task
    galangal complete                       - Move task to done/, create PR
    galangal prompts export                 - Export default prompts for customization
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Galangal Orchestrate - AI-Driven Development Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  galangal init
  galangal start "Add user authentication"
  galangal start "Add auth" --name add-auth-feature
  galangal list
  galangal switch add-auth-feature
  galangal status
  galangal resume
  galangal pause
  galangal approve
  galangal approve-design
  galangal skip-design
  galangal skip-to DEV
  galangal skip-to TEST --resume
  galangal complete
  galangal reset
  galangal prompts export

Task Types:
  At task start, you'll select from:
    [1] Feature   - New functionality (full workflow)
    [2] Bug Fix   - Fix broken behavior (skip design)
    [3] Refactor  - Restructure code (skip design, security)
    [4] Chore     - Dependencies, config, tooling
    [5] Docs      - Documentation only (minimal stages)
    [6] Hotfix    - Critical fix (expedited)

Workflow:
  PM -> DESIGN -> PREFLIGHT -> DEV -> MIGRATION* -> TEST ->
  CONTRACT* -> QA -> BENCHMARK* -> SECURITY -> REVIEW -> DOCS -> COMPLETE

  * = Conditional stages (auto-skipped if condition not met)

Tip: Press Ctrl+C during execution to pause gracefully.
        """,
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
    start_parser.add_argument(
        "--name", "-n", help="Task name (auto-generated if not provided)"
    )
    start_parser.add_argument(
        "--type", "-t",
        choices=["feature", "bugfix", "refactor", "chore", "docs", "hotfix", "1", "2", "3", "4", "5", "6"],
        help="Task type (skip interactive selection)"
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
    resume_parser.set_defaults(func=_cmd_resume)

    # pause
    pause_parser = subparsers.add_parser("pause", help="Pause task for break/shutdown")
    pause_parser.set_defaults(func=_cmd_pause)

    # status
    status_parser = subparsers.add_parser("status", help="Show active task status")
    status_parser.set_defaults(func=_cmd_status)

    # approve
    approve_parser = subparsers.add_parser("approve", help="Record plan approval")
    approve_parser.set_defaults(func=_cmd_approve)

    # approve-design
    approve_design_parser = subparsers.add_parser(
        "approve-design", help="Record design review approval"
    )
    approve_design_parser.set_defaults(func=_cmd_approve_design)

    # skip-design
    skip_design_parser = subparsers.add_parser(
        "skip-design", help="Skip design stage for trivial tasks"
    )
    skip_design_parser.set_defaults(func=_cmd_skip_design)

    # skip-security
    skip_security_parser = subparsers.add_parser(
        "skip-security", help="Skip security stage for non-code changes"
    )
    skip_security_parser.set_defaults(func=_cmd_skip_security)

    # skip-migration
    skip_migration_parser = subparsers.add_parser(
        "skip-migration", help="Skip migration stage"
    )
    skip_migration_parser.set_defaults(func=_cmd_skip_migration)

    # skip-contract
    skip_contract_parser = subparsers.add_parser(
        "skip-contract", help="Skip contract stage"
    )
    skip_contract_parser.set_defaults(func=_cmd_skip_contract)

    # skip-benchmark
    skip_benchmark_parser = subparsers.add_parser(
        "skip-benchmark", help="Skip benchmark stage"
    )
    skip_benchmark_parser.set_defaults(func=_cmd_skip_benchmark)

    # skip-to
    skip_to_parser = subparsers.add_parser(
        "skip-to", help="Jump to a specific stage (for debugging/re-running)"
    )
    skip_to_parser.add_argument(
        "stage", help="Target stage (e.g., DEV, TEST, SECURITY)"
    )
    skip_to_parser.add_argument(
        "--force", "-f", action="store_true", help="Skip confirmation"
    )
    skip_to_parser.add_argument(
        "--resume", "-r", action="store_true", help="Resume workflow immediately after jumping"
    )
    skip_to_parser.set_defaults(func=_cmd_skip_to)

    # reset
    reset_parser = subparsers.add_parser("reset", help="Delete active task")
    reset_parser.add_argument(
        "--force", "-f", action="store_true", help="Skip confirmation"
    )
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
    prompts_show = prompts_subparsers.add_parser(
        "show", help="Show effective prompt for a stage"
    )
    prompts_show.add_argument("stage", help="Stage name (e.g., pm, dev, test)")
    prompts_show.set_defaults(func=_cmd_prompts_show)

    args = parser.parse_args()
    return args.func(args)


# Command wrappers that import lazily to speed up CLI startup
def _cmd_init(args):
    from galangal.commands.init import cmd_init
    return cmd_init(args)


def _cmd_start(args):
    from galangal.commands.start import cmd_start
    return cmd_start(args)


def _cmd_list(args):
    from galangal.commands.list import cmd_list
    return cmd_list(args)


def _cmd_switch(args):
    from galangal.commands.switch import cmd_switch
    return cmd_switch(args)


def _cmd_resume(args):
    from galangal.commands.resume import cmd_resume
    return cmd_resume(args)


def _cmd_pause(args):
    from galangal.commands.pause import cmd_pause
    return cmd_pause(args)


def _cmd_status(args):
    from galangal.commands.status import cmd_status
    return cmd_status(args)


def _cmd_approve(args):
    from galangal.commands.approve import cmd_approve
    return cmd_approve(args)


def _cmd_approve_design(args):
    from galangal.commands.approve import cmd_approve_design
    return cmd_approve_design(args)


def _cmd_skip_design(args):
    from galangal.commands.skip import cmd_skip_design
    return cmd_skip_design(args)


def _cmd_skip_security(args):
    from galangal.commands.skip import cmd_skip_security
    return cmd_skip_security(args)


def _cmd_skip_migration(args):
    from galangal.commands.skip import cmd_skip_migration
    return cmd_skip_migration(args)


def _cmd_skip_contract(args):
    from galangal.commands.skip import cmd_skip_contract
    return cmd_skip_contract(args)


def _cmd_skip_benchmark(args):
    from galangal.commands.skip import cmd_skip_benchmark
    return cmd_skip_benchmark(args)


def _cmd_skip_to(args):
    from galangal.commands.skip import cmd_skip_to
    return cmd_skip_to(args)


def _cmd_reset(args):
    from galangal.commands.reset import cmd_reset
    return cmd_reset(args)


def _cmd_complete(args):
    from galangal.commands.complete import cmd_complete
    return cmd_complete(args)


def _cmd_prompts_export(args):
    from galangal.commands.prompts import cmd_prompts_export
    return cmd_prompts_export(args)


def _cmd_prompts_show(args):
    from galangal.commands.prompts import cmd_prompts_show
    return cmd_prompts_show(args)


if __name__ == "__main__":
    sys.exit(main())
