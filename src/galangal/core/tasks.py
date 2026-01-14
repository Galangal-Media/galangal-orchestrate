"""
Task directory management - creating, listing, and switching tasks.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from galangal.config.loader import (
    get_active_file,
    get_config,
    get_done_dir,
    get_project_root,
    get_tasks_dir,
)
from galangal.core.artifacts import run_command

if TYPE_CHECKING:
    from galangal.core.state import WorkflowState


def get_active_task() -> str | None:
    """Get the currently active task name."""
    active_file = get_active_file()
    if active_file.exists():
        return active_file.read_text().strip()
    return None


def set_active_task(task_name: str) -> None:
    """Set the active task."""
    tasks_dir = get_tasks_dir()
    tasks_dir.mkdir(parents=True, exist_ok=True)
    get_active_file().write_text(task_name)


def clear_active_task() -> None:
    """Clear the active task."""
    active_file = get_active_file()
    if active_file.exists():
        active_file.unlink()


def get_task_dir(task_name: str) -> Path:
    """Get the directory for a task."""
    return get_tasks_dir() / task_name


def list_tasks() -> list[tuple[str, str, str, str]]:
    """List all tasks. Returns [(name, stage, task_type, description), ...]."""
    tasks = []
    tasks_dir = get_tasks_dir()
    if not tasks_dir.exists():
        return tasks

    for task_dir in tasks_dir.iterdir():
        if (
            task_dir.is_dir()
            and not task_dir.name.startswith(".")
            and task_dir.name != "done"
        ):
            state_file = task_dir / "state.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        data = json.load(f)
                        tasks.append(
                            (
                                task_dir.name,
                                data.get("stage", "?"),
                                data.get("task_type", "feature"),
                                data.get("task_description", "")[:50],
                            )
                        )
                except (json.JSONDecodeError, KeyError):
                    tasks.append((task_dir.name, "?", "?", "(invalid state)"))
    return sorted(tasks)


def generate_task_name_ai(description: str) -> str | None:
    """Use AI to generate a concise, meaningful task name."""
    prompt = f"""Generate a short task name for this description. Rules:
- 2-4 words, kebab-case (e.g., fix-auth-bug, add-user-export)
- No prefix, just the name itself
- Capture the essence of the task
- Use action verbs (fix, add, update, refactor, implement)

Description: {description}

Reply with ONLY the task name, nothing else."""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=get_project_root(),
        )
        if result.returncode == 0 and result.stdout.strip():
            # Clean the response - extract just the task name
            name = result.stdout.strip().lower()
            # Remove any quotes, backticks, or extra text
            name = re.sub(r"[`\"']", "", name)
            # Take only first line if multiple
            name = name.split("\n")[0].strip()
            # Validate it looks like a task name (kebab-case, reasonable length)
            if re.match(r"^[a-z][a-z0-9-]{2,40}$", name) and name.count("-") <= 5:
                return name
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return None


def generate_task_name_fallback(description: str) -> str:
    """Fallback: Generate task name from description using simple word extraction."""
    words = description.lower().split()[:4]
    cleaned = [re.sub(r"[^a-z0-9]", "", w) for w in words]
    cleaned = [w for w in cleaned if w]
    name = "-".join(cleaned)
    return name if name else f"task-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def generate_task_name(description: str) -> str:
    """Generate a task name from description using AI with fallback."""
    # Try AI-generated name first
    ai_name = generate_task_name_ai(description)
    if ai_name:
        return ai_name

    # Fallback to simple extraction
    return generate_task_name_fallback(description)


def task_name_exists(name: str) -> bool:
    """Check if task name exists in active or done folders."""
    return get_task_dir(name).exists() or (get_done_dir() / name).exists()


def generate_unique_task_name(
    description: str,
    prefix: str | None = None,
) -> str:
    """Generate a unique task name with automatic suffix if needed.

    Uses AI to generate a meaningful task name from the description,
    then ensures uniqueness by appending a numeric suffix if the name
    already exists.

    Args:
        description: Task description to generate name from.
        prefix: Optional prefix (e.g., "issue-123") to prepend to the name.

    Returns:
        A unique task name that doesn't conflict with existing tasks.
    """
    base_name = generate_task_name(description)

    if prefix:
        base_name = f"{prefix}-{base_name}"

    # Find unique name with suffix if needed
    final_name = base_name
    suffix = 2
    while task_name_exists(final_name):
        final_name = f"{base_name}-{suffix}"
        suffix += 1

    return final_name


def create_task_branch(task_name: str) -> tuple[bool, str]:
    """Create a git branch for the task."""
    config = get_config()
    branch_name = config.branch_pattern.format(task_name=task_name)

    # Check if branch already exists
    code, out, _ = run_command(["git", "branch", "--list", branch_name])
    if out.strip():
        return True, f"Branch {branch_name} already exists"

    # Create and checkout new branch
    code, out, err = run_command(["git", "checkout", "-b", branch_name])
    if code != 0:
        return False, f"Failed to create branch: {err}"

    return True, f"Created branch: {branch_name}"


def get_current_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def ensure_active_task_with_state(
    no_task_msg: str = "No active task.",
    no_state_msg: str = "Could not load state for '{task}'.",
) -> tuple[str, WorkflowState] | tuple[None, None]:
    """Load active task and its state, with error handling.

    This helper consolidates the common pattern of loading the active task
    and its state, with appropriate error messages for each failure case.

    Args:
        no_task_msg: Message to print if no active task.
        no_state_msg: Message template if state can't be loaded.
            Use {task} placeholder for task name.

    Returns:
        Tuple of (task_name, state) if successful,
        or (None, None) with error printed if failed.
    """
    from galangal.core.state import load_state
    from galangal.ui.console import print_error

    active = get_active_task()
    if not active:
        print_error(no_task_msg)
        return None, None

    state = load_state(active)
    if state is None:
        print_error(no_state_msg.format(task=active))
        return None, None

    return active, state
