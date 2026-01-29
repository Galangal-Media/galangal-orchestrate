"""
Task directory management - creating, listing, and switching tasks.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
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


def list_tasks() -> list[tuple[str, str, str, str]]:
    """List all tasks. Returns [(name, stage, task_type, description), ...]."""
    tasks = []
    tasks_dir = get_tasks_dir()
    if not tasks_dir.exists():
        return tasks

    for task_dir in tasks_dir.iterdir():
        if task_dir.is_dir() and not task_dir.name.startswith(".") and task_dir.name != "done":
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
    """Use AI to generate a concise, meaningful task name.

    Uses the configured AI backend from config.ai.default with fallback support.
    """
    from galangal.ai import get_backend_with_fallback

    prompt = f"""Generate a short task name for this description. Rules:
- 2-4 words, kebab-case (e.g., fix-auth-bug, add-user-export)
- No prefix, just the name itself
- Capture the essence of the task
- Use action verbs (fix, add, update, refactor, implement)

Description: {description}

Reply with ONLY the task name, nothing else."""

    try:
        config = get_config()
        backend = get_backend_with_fallback(config.ai.default, config=config)
        result = backend.generate_text(prompt, timeout=30)

        if result:
            # Clean the response - extract just the task name
            name = result.strip().lower()
            # Remove any quotes, backticks, or extra text
            name = re.sub(r"[`\"']", "", name)
            # Take only first line if multiple
            name = name.split("\n")[0].strip()
            # Validate it looks like a task name (kebab-case, reasonable length)
            if re.match(r"^[a-z][a-z0-9-]{2,40}$", name) and name.count("-") <= 5:
                return name
    except (ValueError, Exception):
        # ValueError: no backend available; Exception: other errors
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


# Safe pattern for task names: alphanumeric, hyphens, underscores
# Must start with letter/number, max 60 chars
TASK_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$")


def is_valid_task_name(name: str) -> tuple[bool, str]:
    """
    Validate a task name for safety and format.

    Task names must:
    - Start with a letter or number
    - Contain only alphanumeric characters, hyphens, and underscores
    - Be 1-60 characters long

    This prevents shell injection via task names used in validation commands.

    Args:
        name: The task name to validate.

    Returns:
        Tuple of (is_valid, error_message). Error message is empty if valid.
    """
    if not name:
        return False, "Task name cannot be empty"

    if len(name) > 60:
        return False, "Task name must be 60 characters or less"

    if not TASK_NAME_PATTERN.match(name):
        return (
            False,
            "Task name must start with letter/number and contain only alphanumeric, hyphens, underscores",
        )

    return True, ""


def task_name_exists(name: str) -> bool:
    """Check if task name exists in active or done folders."""
    return (get_tasks_dir() / name).exists() or (get_done_dir() / name).exists()


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
        # Branch exists - check it out to ensure we're on it
        code, out, err = run_command(["git", "checkout", branch_name])
        if code != 0:
            return False, f"Branch {branch_name} exists but checkout failed: {err}"
        return True, f"Checked out existing branch: {branch_name}"

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


def is_on_base_branch() -> tuple[bool, str, str]:
    """
    Check if the repo is on the configured base branch.

    Returns:
        Tuple of (is_on_base, current_branch, base_branch)
    """
    config = get_config()
    base_branch = config.pr.base_branch
    current_branch = get_current_branch()
    return current_branch == base_branch, current_branch, base_branch


def switch_to_base_branch() -> tuple[bool, str]:
    """
    Switch to the configured base branch.

    Returns:
        Tuple of (success, message)
    """
    config = get_config()
    base_branch = config.pr.base_branch

    code, out, err = run_command(["git", "checkout", base_branch])
    if code != 0:
        return False, f"Failed to switch to {base_branch}: {err}"

    return True, f"Switched to {base_branch}"


def pull_base_branch() -> tuple[bool, str]:
    """
    Pull the latest changes from the remote base branch.

    Returns:
        Tuple of (success, message)
    """
    config = get_config()
    base_branch = config.pr.base_branch

    code, out, err = run_command(["git", "pull", "origin", base_branch])
    if code != 0:
        # Check if it's a "no tracking" error - try without remote name
        if "no tracking information" in err.lower():
            code, out, err = run_command(["git", "pull"])
            if code != 0:
                return False, f"Failed to pull: {err}"
        else:
            return False, f"Failed to pull from origin/{base_branch}: {err}"

    return True, f"Pulled latest from {base_branch}"


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


@dataclass
class TaskFromIssueResult:
    """Result of creating a task from a GitHub issue."""

    success: bool
    message: str
    task_name: str | None = None
    screenshots: list[str] | None = None


def create_task_from_issue(
    issue: GitHubIssue,
    repo_name: str | None = None,
    task_name_override: str | None = None,
    mark_in_progress: bool = True,
) -> TaskFromIssueResult:
    """
    Create a task from a GitHub issue with all associated setup.

    This consolidates the task creation flow that was duplicated across
    start.py, tui_runner.py, and github.py. Handles:
    - Ensuring we're on the base branch with latest changes
    - Task name generation and validation
    - Task creation with GitHub metadata
    - Screenshot download (after task creation)
    - Marking issue as in-progress

    Args:
        issue: The GitHubIssue to create a task from
        repo_name: Optional repo name (owner/repo), fetched if not provided
        task_name_override: Optional override for task name (will be validated)
        mark_in_progress: Whether to mark the issue as in-progress

    Returns:
        TaskFromIssueResult with success status, message, and task details
    """
    from galangal.commands.start import create_task
    from galangal.core.state import TaskType, get_task_dir, load_state, save_state
    from galangal.github.issues import (
        download_issue_screenshots,
        mark_issue_in_progress,
        prepare_issue_for_task,
    )

    # Step 0: Ensure we're on the base branch with latest changes
    on_base, current_branch, base_branch = is_on_base_branch()
    if not on_base:
        # Switch to base branch
        success, message = switch_to_base_branch()
        if not success:
            return TaskFromIssueResult(
                success=False,
                message=f"Failed to switch to {base_branch}: {message}",
            )

    # Pull latest changes from remote
    pull_success, pull_message = pull_base_branch()
    if not pull_success:
        # Non-fatal warning - log but continue (might be offline, etc.)
        # The task can still be created on the current state
        pass

    # Step 1: Extract issue data using existing helper
    issue_data = prepare_issue_for_task(issue, repo_name)

    # Step 2: Infer task type from labels
    task_type = (
        TaskType.from_str(issue_data.task_type_hint)
        if issue_data.task_type_hint
        else TaskType.FEATURE
    )

    # Step 3: Generate or validate task name
    if task_name_override:
        # Validate provided name
        valid, error_msg = is_valid_task_name(task_name_override)
        if not valid:
            return TaskFromIssueResult(
                success=False,
                message=f"Invalid task name: {error_msg}",
            )
        if task_name_exists(task_name_override):
            return TaskFromIssueResult(
                success=False,
                message=f"Task '{task_name_override}' already exists",
            )
        task_name = task_name_override
    else:
        # Generate unique name with issue prefix
        prefix = f"issue-{issue.number}"
        task_name = generate_unique_task_name(issue_data.description, prefix)

    # Step 4: Create the task
    success, message = create_task(
        task_name,
        issue_data.description,
        task_type,
        github_issue=issue.number,
        github_repo=issue_data.github_repo,
    )

    if not success:
        return TaskFromIssueResult(
            success=False,
            message=message,
        )

    # Step 5: Download screenshots AFTER task creation
    screenshots = []
    if issue_data.issue_body:
        try:
            task_dir = get_task_dir(task_name)
            screenshots = download_issue_screenshots(issue_data.issue_body, task_dir)
            if screenshots:
                # Update state with screenshot paths
                state = load_state(task_name)
                if state:
                    state.screenshots = screenshots
                    save_state(state)
        except Exception:
            # Non-critical - continue without screenshots
            pass

    # Step 6: Mark issue as in-progress
    if mark_in_progress:
        try:
            mark_issue_in_progress(issue.number)
        except Exception:
            # Non-critical - continue anyway
            pass

    return TaskFromIssueResult(
        success=True,
        message=message,
        task_name=task_name,
        screenshots=screenshots,
    )


# Type hint import for type checking only
if TYPE_CHECKING:
    from galangal.github.issues import GitHubIssue
