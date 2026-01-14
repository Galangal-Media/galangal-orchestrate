"""
Artifact management - reading and writing task artifacts.
"""

import subprocess
from pathlib import Path

from galangal.config.loader import get_project_root
from galangal.core.state import get_task_dir
from galangal.exceptions import TaskError


def artifact_path(name: str, task_name: str | None = None) -> Path:
    """Get path to an artifact file."""
    from galangal.core.tasks import get_active_task

    if task_name is None:
        task_name = get_active_task()
    if task_name is None:
        raise TaskError("No active task")
    return get_task_dir(task_name) / name


def artifact_exists(name: str, task_name: str | None = None) -> bool:
    """Check if an artifact exists."""
    try:
        return artifact_path(name, task_name).exists()
    except TaskError:
        return False


def read_artifact(name: str, task_name: str | None = None) -> str | None:
    """Read an artifact file."""
    try:
        path = artifact_path(name, task_name)
        if path.exists():
            return path.read_text()
    except TaskError:
        pass
    return None


def write_artifact(name: str, content: str, task_name: str | None = None) -> None:
    """Write an artifact file."""
    path = artifact_path(name, task_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_skip_artifact(stage: str, reason: str, task_name: str | None = None) -> None:
    """Write a standardized skip artifact for a stage.

    Creates a {STAGE}_SKIP.md artifact with consistent formatting.

    Args:
        stage: Stage name (e.g., "MIGRATION", "SECURITY").
        reason: Reason for skipping the stage.
        task_name: Task name, or None to use active task.
    """
    from galangal.core.utils import now_iso

    content = f"""# {stage.upper()} Stage Skipped

Date: {now_iso()}
Reason: {reason}
"""
    write_artifact(f"{stage.upper()}_SKIP.md", content, task_name)


def parse_stage_plan(task_name: str | None = None) -> dict[str, dict] | None:
    """
    Parse STAGE_PLAN.md artifact to extract stage recommendations.

    The STAGE_PLAN.md file contains a markdown table with stage recommendations:
    | Stage | Action | Reason |
    |-------|--------|--------|
    | MIGRATION | skip | No database changes |

    Returns:
        Dictionary mapping stage name to {"action": "skip"|"run", "reason": "..."},
        or None if the artifact doesn't exist or can't be parsed.
    """
    import re

    content = read_artifact("STAGE_PLAN.md", task_name)
    if not content:
        return None

    stage_plan = {}

    # Parse markdown table rows
    # Match lines like: | MIGRATION | skip | No database changes |
    table_row_pattern = re.compile(
        r"^\|\s*(\w+)\s*\|\s*(skip|run)\s*\|\s*(.+?)\s*\|",
        re.IGNORECASE | re.MULTILINE,
    )

    for match in table_row_pattern.finditer(content):
        stage_name = match.group(1).upper()
        action = match.group(2).lower()
        reason = match.group(3).strip()

        # Only track plannable stages
        if stage_name in {"MIGRATION", "CONTRACT", "BENCHMARK", "SECURITY"}:
            stage_plan[stage_name] = {"action": action, "reason": reason}

    return stage_plan if stage_plan else None


def run_command(
    cmd: list[str], cwd: Path | None = None, timeout: int = 300
) -> tuple[int, str, str]:
    """Run a command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or get_project_root(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)
