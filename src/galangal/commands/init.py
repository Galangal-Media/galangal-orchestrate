"""
galangal init - Initialize galangal in a project.
"""

import argparse
from pathlib import Path

from rich.prompt import Confirm, Prompt

from galangal.config.defaults import generate_default_config
from galangal.config.loader import find_project_root
from galangal.ui.console import console, print_info, print_success


def detect_stacks(project_root: Path) -> list[dict[str, str]]:
    """Detect technology stacks in the project."""
    stacks = []

    # Python detection
    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        framework = None
        # Check for framework
        if (project_root / "requirements.txt").exists():
            reqs = (project_root / "requirements.txt").read_text().lower()
            if "fastapi" in reqs:
                framework = "fastapi"
            elif "django" in reqs:
                framework = "django"
            elif "flask" in reqs:
                framework = "flask"
        stacks.append({"language": "python", "framework": framework, "root": None})

    # Check subdirectories for separate stacks
    for subdir in ["backend", "api", "server"]:
        subpath = project_root / subdir
        if subpath.exists():
            if (subpath / "pyproject.toml").exists() or (subpath / "requirements.txt").exists():
                framework = None
                if (subpath / "requirements.txt").exists():
                    reqs = (subpath / "requirements.txt").read_text().lower()
                    if "fastapi" in reqs:
                        framework = "fastapi"
                    elif "django" in reqs:
                        framework = "django"
                # Only add if not already detected at root
                if not any(s.get("root") is None and s["language"] == "python" for s in stacks):
                    stacks.append({"language": "python", "framework": framework, "root": f"{subdir}/"})

    # TypeScript/JavaScript detection
    if (project_root / "package.json").exists():
        pkg = (project_root / "package.json").read_text().lower()
        framework = None
        if "vite" in pkg:
            framework = "vite"
        elif "next" in pkg:
            framework = "next"
        elif "react" in pkg:
            framework = "react"
        elif "vue" in pkg:
            framework = "vue"
        elif "angular" in pkg:
            framework = "angular"
        stacks.append({"language": "typescript", "framework": framework, "root": None})

    # Check subdirectories for frontend
    for subdir in ["frontend", "admin", "web", "client", "app"]:
        subpath = project_root / subdir
        if subpath.exists() and (subpath / "package.json").exists():
            pkg = (subpath / "package.json").read_text().lower()
            framework = None
            if "vite" in pkg:
                framework = "vite"
            elif "next" in pkg:
                framework = "next"
            elif "react" in pkg:
                framework = "react"
            # Only add if not already detected at root
            if not any(s.get("root") is None and s["language"] == "typescript" for s in stacks):
                stacks.append({"language": "typescript", "framework": framework, "root": f"{subdir}/"})

    # PHP detection
    if (project_root / "composer.json").exists():
        composer = (project_root / "composer.json").read_text().lower()
        framework = None
        if "symfony" in composer:
            framework = "symfony"
        elif "laravel" in composer:
            framework = "laravel"
        stacks.append({"language": "php", "framework": framework, "root": None})

    # Go detection
    if (project_root / "go.mod").exists():
        stacks.append({"language": "go", "framework": None, "root": None})

    # Rust detection
    if (project_root / "Cargo.toml").exists():
        stacks.append({"language": "rust", "framework": None, "root": None})

    return stacks


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize galangal in the current project."""
    console.print("\n[bold cyan]╔══════════════════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]              [bold]Galangal Orchestrate[/bold]                          [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]          AI-Driven Development Workflow                     [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════════════════╝[/bold cyan]\n")

    project_root = find_project_root()
    galangal_dir = project_root / ".galangal"

    if galangal_dir.exists():
        print_info(f"Galangal already initialized in {project_root}")
        if not Confirm.ask("Reinitialize?", default=False):
            return 0

    console.print(f"[dim]Project root: {project_root}[/dim]")
    console.print("\n[bold]Scanning project structure...[/bold]\n")

    # Detect stacks
    stacks = detect_stacks(project_root)

    if stacks:
        console.print("[bold]Detected stacks:[/bold]")
        for i, stack in enumerate(stacks, 1):
            framework = f"/{stack['framework']}" if stack.get("framework") else ""
            root = f" ({stack['root']})" if stack.get("root") else ""
            console.print(f"  [{i}] {stack['language'].title()}{framework}{root}")

        if not Confirm.ask("\nIs this correct?", default=True):
            console.print("[dim]You can edit .galangal/config.yaml after initialization.[/dim]")
    else:
        console.print("[yellow]No stacks detected. You can configure them in .galangal/config.yaml[/yellow]")
        stacks = [{"language": "python", "framework": None, "root": None}]

    # Get project name
    default_name = project_root.name
    project_name = Prompt.ask("Project name", default=default_name)

    # Create .galangal directory
    galangal_dir.mkdir(exist_ok=True)
    (galangal_dir / "prompts").mkdir(exist_ok=True)

    # Generate config
    config_content = generate_default_config(
        project_name=project_name,
        stacks=stacks,
    )
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
    console.print("  [cyan]galangal prompts export[/cyan]    # Export defaults to .galangal/prompts/")
    console.print("\nNext steps:")
    console.print("  [cyan]galangal start \"Your first task\"[/cyan]")

    return 0
