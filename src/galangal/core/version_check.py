"""
Version checking utilities for galangal-orchestrate.

Checks PyPI for newer versions and prompts users to update.
"""

from __future__ import annotations

import json
import urllib.request
from typing import NamedTuple

from galangal import __version__

PYPI_PACKAGE_NAME = "galangal-orchestrate"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PACKAGE_NAME}/json"
REQUEST_TIMEOUT = 3  # seconds


class VersionInfo(NamedTuple):
    """Result of a version check."""

    current: str
    latest: str | None
    update_available: bool
    error: str | None = None


def parse_version(version: str) -> tuple[int, ...]:
    """
    Parse a version string into a tuple of integers for comparison.

    Handles versions like "0.13.0", "1.2.3", etc.
    Non-numeric parts (like "rc1", "beta") are ignored.

    Args:
        version: Version string (e.g., "0.13.0")

    Returns:
        Tuple of integers (e.g., (0, 13, 0))
    """
    parts = []
    for part in version.split("."):
        # Extract numeric portion only
        numeric = ""
        for char in part:
            if char.isdigit():
                numeric += char
            else:
                break
        if numeric:
            parts.append(int(numeric))
    return tuple(parts)


def compare_versions(current: str, latest: str) -> int:
    """
    Compare two version strings.

    Args:
        current: Current version string
        latest: Latest version string

    Returns:
        -1 if current < latest (update available)
         0 if current == latest (up to date)
         1 if current > latest (ahead, e.g., dev version)
    """
    current_parts = parse_version(current)
    latest_parts = parse_version(latest)

    # Pad shorter version with zeros
    max_len = max(len(current_parts), len(latest_parts))
    current_parts = current_parts + (0,) * (max_len - len(current_parts))
    latest_parts = latest_parts + (0,) * (max_len - len(latest_parts))

    if current_parts < latest_parts:
        return -1
    elif current_parts > latest_parts:
        return 1
    return 0


def get_latest_version() -> str | None:
    """
    Fetch the latest version from PyPI.

    Returns:
        Latest version string, or None if fetch failed.
    """
    try:
        request = urllib.request.Request(
            PYPI_URL,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
            version = data.get("info", {}).get("version")
            return str(version) if version else None
    except Exception:
        return None


def check_for_updates() -> VersionInfo:
    """
    Check if a newer version is available on PyPI.

    Returns:
        VersionInfo with current/latest versions and update status.
    """
    current = __version__
    latest = get_latest_version()

    if latest is None:
        return VersionInfo(
            current=current,
            latest=None,
            update_available=False,
            error="Could not check PyPI",
        )

    update_available = compare_versions(current, latest) < 0

    return VersionInfo(
        current=current,
        latest=latest,
        update_available=update_available,
    )


def get_update_command() -> str:
    """
    Get the pip command to update galangal-orchestrate.

    Returns:
        Command string for updating the package.
    """
    return f"pip install --upgrade {PYPI_PACKAGE_NAME}"


def check_and_prompt_update() -> bool:
    """
    Check for updates and prompt user if one is available.

    This is designed to be called at the start of `galangal start`.
    It's non-blocking on errors and doesn't interrupt workflow if
    the user declines to update.

    Returns:
        True if user wants to continue (or no update needed).
        False if user wants to quit to update.
    """
    from rich.prompt import Confirm

    from galangal.ui.console import console, print_info

    try:
        info = check_for_updates()

        if info.error:
            # Silently skip if we can't reach PyPI
            return True

        if not info.update_available:
            return True

        # Show update notification
        console.print()
        print_info(
            f"New version available: [cyan]{info.latest}[/cyan] "
            f"(you have {info.current})"
        )
        console.print(f"[dim]  Update with: {get_update_command()}[/dim]\n")

        # Ask if they want to continue or quit to update
        continue_anyway = Confirm.ask(
            "Continue without updating?",
            default=True,
        )

        if not continue_anyway:
            # Offer to run the update
            run_update = Confirm.ask(
                "Run update now?",
                default=True,
            )

            if run_update:
                return _run_update()

            console.print(f"\n[dim]Run: {get_update_command()}[/dim]")
            return False

        console.print()  # Add spacing before TUI starts
        return True

    except Exception:
        # Non-critical, don't interrupt task creation
        return True


def _run_update() -> bool:
    """
    Run pip upgrade and return whether to continue.

    Returns:
        False (user should restart after update).
    """
    import subprocess
    import sys

    from galangal.ui.console import console, print_error, print_success

    console.print("\n[dim]Running update...[/dim]")

    try:
        # Use sys.executable to ensure we use the same Python
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", PYPI_PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            print_success("Update complete! Please restart galangal.")
        else:
            print_error(f"Update failed: {result.stderr[:200]}")
            console.print(f"[dim]Try manually: {get_update_command()}[/dim]")

    except subprocess.TimeoutExpired:
        print_error("Update timed out")
        console.print(f"[dim]Try manually: {get_update_command()}[/dim]")
    except Exception as e:
        print_error(f"Update failed: {e}")
        console.print(f"[dim]Try manually: {get_update_command()}[/dim]")

    return False  # Always return False so user restarts
