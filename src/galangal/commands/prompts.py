"""
galangal prompts - Manage stage prompts.
"""

import argparse
import shutil
from pathlib import Path

from galangal.config.loader import get_prompts_dir
from galangal.core.state import Stage
from galangal.prompts.builder import PromptBuilder
from galangal.ui.console import console, print_error, print_info, print_success


def cmd_prompts_export(args: argparse.Namespace) -> int:
    """Export default prompts to .galangal/prompts/ for customization."""
    prompts_dir = get_prompts_dir()
    defaults_dir = Path(__file__).parent.parent / "prompts" / "defaults"

    if not defaults_dir.exists():
        print_error("Default prompts directory not found.")
        return 1

    prompts_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    skipped = []

    for prompt_file in defaults_dir.glob("*.md"):
        dest = prompts_dir / prompt_file.name
        if dest.exists():
            skipped.append(prompt_file.name)
        else:
            shutil.copy(prompt_file, dest)
            exported.append(prompt_file.name)

    if exported:
        print_success(f"Exported {len(exported)} prompts to .galangal/prompts/")
        for name in exported:
            console.print(f"  [green]✓[/green] {name}")

    if skipped:
        print_info(f"Skipped {len(skipped)} existing prompts (won't overwrite)")
        for name in skipped:
            console.print(f"  [dim]○[/dim] {name}")

    console.print("\n[dim]Edit these files to customize prompts for your project.[/dim]")
    console.print("[dim]Project prompts override package defaults.[/dim]")

    return 0


def cmd_prompts_show(args: argparse.Namespace) -> int:
    """Show the effective prompt for a stage."""
    stage_name = args.stage.upper()

    try:
        stage = Stage.from_str(stage_name)
    except ValueError:
        print_error(f"Invalid stage: '{args.stage}'")
        valid = ", ".join(s.value.lower() for s in Stage if s != Stage.COMPLETE)
        console.print(f"[dim]Valid stages: {valid}[/dim]")
        return 1

    if stage == Stage.COMPLETE:
        print_error("COMPLETE stage has no prompt.")
        return 1

    builder = PromptBuilder()
    prompt = builder.get_stage_prompt(stage)

    # Determine source
    prompts_dir = get_prompts_dir()
    override_path = prompts_dir / f"{stage_name.lower()}.md"
    source = "project override" if override_path.exists() else "package default"

    console.print(f"\n[bold]Stage:[/bold] {stage.value}")
    console.print(f"[bold]Source:[/bold] {source}")
    console.print("[dim]" + "=" * 60 + "[/dim]")
    console.print(prompt)
    console.print("[dim]" + "=" * 60 + "[/dim]")

    return 0


def cmd_prompts(args: argparse.Namespace) -> int:
    """Prompts management command router."""
    if hasattr(args, "prompts_command") and args.prompts_command:
        if args.prompts_command == "export":
            return cmd_prompts_export(args)
        elif args.prompts_command == "show":
            return cmd_prompts_show(args)

    console.print("Usage: galangal prompts <command>")
    console.print("\nCommands:")
    console.print("  export    Export default prompts for customization")
    console.print("  show      Show effective prompt for a stage")
    return 1
