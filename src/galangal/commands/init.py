"""
galangal init - Initialize galangal in a project.
"""

import argparse

from rich.prompt import Confirm, Prompt

from galangal.config.defaults import generate_default_config
from galangal.config.loader import find_project_root
from galangal.ui.console import console, print_info, print_success


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize galangal in the current project."""
    console.print(
        "\n[bold cyan]╔══════════════════════════════════════════════════════════════╗[/bold cyan]"
    )
    console.print(
        "[bold cyan]║[/bold cyan]              [bold]Galangal Orchestrate[/bold]                          [bold cyan]║[/bold cyan]"
    )
    console.print(
        "[bold cyan]║[/bold cyan]          AI-Driven Development Workflow                     [bold cyan]║[/bold cyan]"
    )
    console.print(
        "[bold cyan]╚══════════════════════════════════════════════════════════════╝[/bold cyan]\n"
    )

    project_root = find_project_root()
    galangal_dir = project_root / ".galangal"

    if galangal_dir.exists():
        print_info(f"Galangal already initialized in {project_root}")
        if not Confirm.ask("Reinitialize?", default=False):
            return 0

    console.print(f"[dim]Project root: {project_root}[/dim]\n")

    # Get project name
    default_name = project_root.name
    project_name = Prompt.ask("Project name", default=default_name)

    # Create .galangal directory
    galangal_dir.mkdir(exist_ok=True)
    (galangal_dir / "prompts").mkdir(exist_ok=True)

    # Generate config
    config_content = generate_default_config(project_name=project_name)
    (galangal_dir / "config.yaml").write_text(config_content)

    print_success("Created .galangal/config.yaml")
    print_success("Created .galangal/prompts/ (empty - uses defaults)")

    # Add to .gitignore
    gitignore = project_root / ".gitignore"
    tasks_entry = "galangal-tasks/"
    if gitignore.exists():
        content = gitignore.read_text()
        if tasks_entry not in content:
            with open(gitignore, "a") as f:
                f.write(f"\n# Galangal task artifacts\n{tasks_entry}\n")
            print_success(f"Added {tasks_entry} to .gitignore")
    else:
        gitignore.write_text(f"# Galangal task artifacts\n{tasks_entry}\n")
        print_success(f"Created .gitignore with {tasks_entry}")

    console.print("\n[bold green]Initialization complete![/bold green]\n")
    console.print("To customize prompts for your project:")
    console.print(
        "  [cyan]galangal prompts export[/cyan]    # Export defaults to .galangal/prompts/"
    )
    console.print("\nNext steps:")
    console.print('  [cyan]galangal start "Your first task"[/cyan]')
    console.print("\nFor GitHub Issues integration:")
    console.print("  [cyan]galangal github setup[/cyan]      # Create labels and configure")

    return 0
