"""
Artifact management - reading and writing task artifacts.
"""

import subprocess
from pathlib import Path
from typing import Optional

from galangal.config.loader import get_project_root
from galangal.core.state import get_task_dir


def artifact_path(name: str, task_name: Optional[str] = None) -> Path:
    """Get path to an artifact file."""
    from galangal.core.tasks import get_active_task

    if task_name is None:
        task_name = get_active_task()
    if task_name is None:
        raise ValueError("No active task")
    return get_task_dir(task_name) / name


def artifact_exists(name: str, task_name: Optional[str] = None) -> bool:
    """Check if an artifact exists."""
    try:
        return artifact_path(name, task_name).exists()
    except ValueError:
        return False


def read_artifact(name: str, task_name: Optional[str] = None) -> Optional[str]:
    """Read an artifact file."""
    try:
        path = artifact_path(name, task_name)
        if path.exists():
            return path.read_text()
    except ValueError:
        pass
    return None


def write_artifact(name: str, content: str, task_name: Optional[str] = None) -> None:
    """Write an artifact file."""
    path = artifact_path(name, task_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run_command(
    cmd: list[str], cwd: Optional[Path] = None, timeout: int = 300
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
