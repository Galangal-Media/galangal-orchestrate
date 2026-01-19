"""
galangal init - Initialize galangal in a project.
"""

import argparse

import yaml
from rich.prompt import Confirm, Prompt

from galangal.config.defaults import generate_default_config
from galangal.config.loader import find_project_root
from galangal.ui.console import console, print_info, print_success, print_warning


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
    config_file = galangal_dir / "config.yaml"

    # Check for --quick flag (non-interactive mode)
    quick_mode = getattr(args, "quick", False)

    if galangal_dir.exists():
        existing_config = None
        if config_file.exists():
            try:
                existing_config = yaml.safe_load(config_file.read_text())
            except yaml.YAMLError:
                existing_config = None

        if existing_config and not quick_mode:
            # Check for missing sections
            from galangal.commands.init_wizard import check_missing_sections

            missing = check_missing_sections(existing_config)

            if missing:
                print_info(f"Galangal already initialized in {project_root}")
                print_warning(f"Missing configuration sections: {', '.join(missing)}")

                if Confirm.ask("Run setup wizard to configure missing sections?", default=True):
                    return _run_wizard_update(project_root, galangal_dir, existing_config)
            else:
                print_info(f"Galangal already initialized in {project_root}")

            if Confirm.ask("Reinitialize with setup wizard?", default=False):
                return _run_wizard_new(project_root, galangal_dir)

            return 0
        else:
            print_info(f"Galangal already initialized in {project_root}")
            if not Confirm.ask("Reinitialize?", default=False):
                return 0

    console.print(f"[dim]Project root: {project_root}[/dim]\n")

    # Decide between wizard and quick mode
    if quick_mode:
        return _run_quick_init(project_root, galangal_dir)
    else:
        use_wizard = Confirm.ask(
            "Run interactive setup wizard? (recommended for first-time setup)",
            default=True,
        )

        if use_wizard:
            return _run_wizard_new(project_root, galangal_dir)
        else:
            return _run_quick_init(project_root, galangal_dir)


def _run_wizard_new(project_root, galangal_dir) -> int:
    """Run the full setup wizard for new initialization."""
    from galangal.commands.init_wizard import run_wizard

    config = run_wizard(project_root, existing_config=None)

    # Create directories
    galangal_dir.mkdir(exist_ok=True)
    (galangal_dir / "prompts").mkdir(exist_ok=True)

    # Write config
    config_content = config.to_yaml()
    (galangal_dir / "config.yaml").write_text(config_content)

    print_success("Created .galangal/config.yaml")
    print_success("Created .galangal/prompts/ (empty - uses defaults)")

    # Add to .gitignore
    _update_gitignore(project_root)

    _show_next_steps()
    return 0


def _run_wizard_update(project_root, galangal_dir, existing_config: dict) -> int:
    """Run the setup wizard in update mode for missing sections."""
    from galangal.commands.init_wizard import run_wizard

    config = run_wizard(project_root, existing_config=existing_config)

    # Write updated config
    config_content = config.to_yaml()
    (galangal_dir / "config.yaml").write_text(config_content)

    print_success("Updated .galangal/config.yaml")

    _show_next_steps()
    return 0


def _run_quick_init(project_root, galangal_dir) -> int:
    """Run quick initialization without wizard (original behavior)."""
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
    _update_gitignore(project_root)

    console.print("\n[dim]Tip: Run 'galangal init' again to use the setup wizard.[/dim]")
    _show_next_steps()
    return 0


def _update_gitignore(project_root) -> None:
    """Add galangal-tasks/ to .gitignore if not present."""
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


def _show_next_steps() -> None:
    """Show next steps after initialization."""
    console.print("\n[bold green]Initialization complete![/bold green]\n")
    console.print("To customize prompts for your project:")
    console.print(
        "  [cyan]galangal prompts export[/cyan]    # Export defaults to .galangal/prompts/"
    )
    console.print("\nNext steps:")
    console.print('  [cyan]galangal start "Your first task"[/cyan]')
    console.print("\nFor GitHub Issues integration:")
    console.print("  [cyan]galangal github setup[/cyan]      # Create labels and configure")
