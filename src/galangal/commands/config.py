"""
Configuration management commands.
"""

import argparse
import json

from galangal.config.loader import get_project_root, is_initialized
from galangal.config.schema import GalangalConfig
from galangal.ui.console import console, print_error, print_info, print_success


def cmd_config_edit(args: argparse.Namespace) -> int:
    """Launch interactive config editor TUI."""
    if not is_initialized():
        print_error("Galangal has not been initialized in this project.")
        print_info("Run 'galangal init' first to set up your project.")
        return 1

    config_path = get_project_root() / ".galangal" / "config.yaml"

    from galangal.ui.tui.config_editor import run_config_editor

    saved = run_config_editor(config_path)

    if saved:
        print_success("Configuration saved successfully.")
    else:
        print_info("No changes made.")

    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    """Show current configuration."""
    if not is_initialized():
        print_error("Galangal has not been initialized in this project.")
        print_info("Run 'galangal init' first to set up your project.")
        return 1

    from galangal.config.loader import get_config

    config = get_config()

    if args.json:
        # Output as JSON for scripting
        console.print(json.dumps(config.model_dump(), indent=2))
    else:
        # Pretty print with sections
        import yaml

        console.print("[bold #fe8019]Current Configuration[/]\n")
        console.print(yaml.dump(config.model_dump(), default_flow_style=False, sort_keys=False))

    return 0


def cmd_config_schema(args: argparse.Namespace) -> int:
    """Export JSON Schema for config.yaml."""
    schema = GalangalConfig.model_json_schema()
    console.print(json.dumps(schema, indent=2))
    return 0


def cmd_config_validate(args: argparse.Namespace) -> int:
    """Validate current configuration."""
    if not is_initialized():
        print_error("Galangal has not been initialized in this project.")
        print_info("Run 'galangal init' first to set up your project.")
        return 1

    config_path = get_project_root() / ".galangal" / "config.yaml"

    if not config_path.exists():
        print_info("No config file found. Using defaults.")
        return 0

    import yaml
    from pydantic import ValidationError

    try:
        data = yaml.safe_load(config_path.read_text()) or {}
        GalangalConfig.model_validate(data)
        print_success("Configuration is valid.")
        return 0
    except yaml.YAMLError as e:
        print_error(f"Invalid YAML: {e}")
        return 1
    except ValidationError as e:
        print_error("Configuration validation failed:")
        for error in e.errors():
            loc = ".".join(str(x) for x in error["loc"])
            console.print(f"  [#fb4934]{loc}[/]: {error['msg']}")
        return 1
