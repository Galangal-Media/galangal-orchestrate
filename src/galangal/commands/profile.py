"""
galangal profile - Quick AI backend profile switching.
"""

import argparse

import yaml

from galangal.config.loader import get_config, get_project_root, require_initialized
from galangal.ui.console import console, print_error, print_info, print_success


def cmd_profile_show(args: argparse.Namespace) -> int:
    """Show the active AI profile and its routing table."""
    if not require_initialized():
        return 1

    config = get_config()
    profile_name = config.ai.profile

    if not profile_name:
        print_info("No active profile. Using top-level ai.default and ai.stage_backends.")
        console.print(f"  default: [bold]{config.ai.default}[/]")
        if config.ai.stage_backends:
            for stage, backend in sorted(config.ai.stage_backends.items()):
                console.print(f"  {stage}: {backend}")
        return 0

    console.print(f"[bold #fe8019]Active profile:[/] {profile_name}\n")
    console.print(f"  default: [bold]{config.ai.default}[/]")
    if config.ai.stage_backends:
        for stage, backend in sorted(config.ai.stage_backends.items()):
            console.print(f"  {stage}: {backend}")
    if config.peer_review.enabled:
        console.print(f"  peer_review: {config.peer_review.backend}")

    return 0


def cmd_profile_list(args: argparse.Namespace) -> int:
    """List all defined AI profiles."""
    if not require_initialized():
        return 1

    config = get_config()

    if not config.ai.profiles:
        print_info("No profiles defined. Add profiles under ai.profiles in config.yaml.")
        return 0

    active = config.ai.profile
    console.print("[bold #fe8019]AI Profiles[/]\n")

    for name, profile in config.ai.profiles.items():
        marker = " [bold green]*[/]" if name == active else ""
        console.print(f"  [bold]{name}[/]{marker}")
        console.print(f"    default: {profile.default}")
        if profile.stage_backends:
            stages = ", ".join(f"{s}={b}" for s, b in sorted(profile.stage_backends.items()))
            console.print(f"    stages:  {stages}")
        if profile.peer_review_backend:
            console.print(f"    peer_review: {profile.peer_review_backend}")
        console.print()

    return 0


def cmd_profile_switch(args: argparse.Namespace) -> int:
    """Switch the active AI profile by updating config.yaml."""
    if not require_initialized():
        return 1

    name = args.name
    config = get_config()

    if name not in config.ai.profiles:
        print_error(
            f"Profile '{name}' not found. "
            f"Available: {', '.join(sorted(config.ai.profiles)) or '(none)'}"
        )
        return 1

    config_path = get_project_root() / ".galangal" / "config.yaml"
    data = yaml.safe_load(config_path.read_text()) or {}

    # Ensure ai section exists
    if "ai" not in data:
        data["ai"] = {}

    data["ai"]["profile"] = name

    config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    profile = config.ai.profiles[name]
    print_success(f"Switched to profile '{name}' (default: {profile.default})")

    return 0
