"""Git utilities for per-stage commits and squashing."""

from pathlib import Path

from galangal.core.artifacts import run_command


def get_current_head(cwd: Path | None = None) -> str | None:
    """Get current HEAD commit SHA.

    Args:
        cwd: Working directory, defaults to project root.

    Returns:
        HEAD commit SHA, or None if not in a git repo.
    """
    code, out, _ = run_command(["git", "rev-parse", "HEAD"], cwd=cwd)
    return out.strip() if code == 0 and out.strip() else None


def has_changes_to_commit(cwd: Path | None = None) -> bool:
    """Check if there are uncommitted changes.

    Args:
        cwd: Working directory, defaults to project root.

    Returns:
        True if there are uncommitted changes to commit.
    """
    code, out, _ = run_command(["git", "status", "--porcelain"], cwd=cwd)
    return code == 0 and bool(out.strip())


def create_wip_commit(
    stage: str,
    task_name: str,
    cwd: Path | None = None,
) -> tuple[str | None, str | None]:
    """Create a WIP commit for a stage.

    Args:
        stage: Stage name (e.g., "DEV", "TEST").
        task_name: Task name for commit message.
        cwd: Working directory, defaults to project root.

    Returns:
        Tuple of (sha, error): sha is the new HEAD SHA if commit was created,
        error is an error message if commit failed. Both None means no changes.
    """
    # Check if there are changes to commit
    if not has_changes_to_commit(cwd):
        return None, None

    # Stage all changes (respects .gitignore)
    code, out, err = run_command(["git", "add", "-A"], cwd=cwd)
    if code != 0:
        return None, f"git add failed: {err or out}"

    # Check if anything was staged
    code, staged_out, _ = run_command(["git", "diff", "--cached", "--name-only"], cwd=cwd)
    if code != 0 or not staged_out.strip():
        # Nothing staged, reset and return
        run_command(["git", "reset", "HEAD"], cwd=cwd)
        return None, None

    # Create commit
    commit_msg = f"wip({stage}): stage changes for {task_name}"
    code, out, err = run_command(["git", "commit", "-m", commit_msg], cwd=cwd)
    if code != 0:
        # Reset staged changes so we don't leave dirty state
        run_command(["git", "reset", "HEAD"], cwd=cwd)
        return None, f"git commit failed: {err or out}"

    # Return new HEAD SHA
    return get_current_head(cwd), None


def squash_to_base(base_sha: str, commit_msg: str, cwd: Path | None = None) -> bool:
    """Soft reset to base and create final commit with given message.

    This squashes all commits since base_sha into a single commit.

    Args:
        base_sha: Base commit SHA to reset to.
        commit_msg: Final commit message for the squashed commit.
        cwd: Working directory, defaults to project root.

    Returns:
        True if squash succeeded, False otherwise.
    """
    # Verify base_sha exists
    code, _, _ = run_command(["git", "cat-file", "-t", base_sha], cwd=cwd)
    if code != 0:
        return False

    # Soft reset to base (keeps working tree and index intact)
    code, _, err = run_command(["git", "reset", "--soft", base_sha], cwd=cwd)
    if code != 0:
        return False

    # Check if there's anything to commit after reset
    code, staged_out, _ = run_command(["git", "diff", "--cached", "--name-only"], cwd=cwd)
    if code != 0 or not staged_out.strip():
        # Nothing to commit - this shouldn't happen normally
        return True

    # Create the squashed commit
    code, _, err = run_command(["git", "commit", "-m", commit_msg], cwd=cwd)
    return code == 0


def get_commits_since_base(base_sha: str, cwd: Path | None = None) -> list[dict[str, str]]:
    """Get list of commits since base SHA.

    Args:
        base_sha: Base commit SHA.
        cwd: Working directory.

    Returns:
        List of dicts with "sha" and "message" keys, newest first.
    """
    # Get commits from base to HEAD
    code, out, _ = run_command(
        ["git", "log", "--format=%H|%s", f"{base_sha}..HEAD"],
        cwd=cwd,
    )

    if code != 0 or not out.strip():
        return []

    commits = []
    for line in out.strip().split("\n"):
        if "|" in line:
            sha, msg = line.split("|", 1)
            commits.append({"sha": sha.strip(), "message": msg.strip()})

    return commits
