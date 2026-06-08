"""
Async git operations for environment management.

All operations use asyncio.create_subprocess_exec following hub patterns.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Allowed remote URL schemes for clone. Excludes file:// and the ext:: transport
# helper (which can execute commands) and local paths (which can exfiltrate files).
_ALLOWED_URL_RE = re.compile(r"^(https?|git|ssh)://", re.IGNORECASE)
# git's scp-like syntax: user@host:path
_SCP_LIKE_RE = re.compile(r"^[\w.+-]+@[\w.-]+:")
# A conservative branch/ref allowlist (no leading '-', no '..', no whitespace).
_BRANCH_RE = re.compile(r"^[\w][\w./-]*$")


class GitError(Exception):
    """Raised when a git operation fails."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def _validate_repo_url(url: str) -> str:
    """Reject local/ext/option-injection URLs; allow only network git schemes."""
    if not url or url.startswith("-"):
        raise GitError(f"Invalid repository URL: {url!r}")
    if _ALLOWED_URL_RE.match(url) or _SCP_LIKE_RE.match(url):
        return url
    raise GitError(
        f"Refusing to clone {url!r}: only http(s)/git/ssh URLs are allowed "
        "(file://, ext::, and local paths are blocked)."
    )


def _validate_branch(branch: str) -> str:
    """Reject branch names that could be interpreted as git options or escapes."""
    if not branch or not _BRANCH_RE.match(branch) or ".." in branch:
        raise GitError(f"Invalid branch name: {branch!r}")
    return branch


async def _run_git(
    *args: str,
    cwd: str | Path | None = None,
    timeout: float = 300,
) -> str:
    """Run a git command and return stdout.

    Dangerous transports are disabled globally (defense in depth): the ext::
    helper can run arbitrary commands and file:// can read local files.
    """
    cmd = [
        "git",
        "-c", "protocol.ext.allow=never",
        "-c", "protocol.file.allow=never",
        *args,
    ]
    logger.debug(f"Running: {' '.join(cmd)} in {cwd or '.'}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitError(f"Git command timed out after {timeout}s: {' '.join(cmd)}")

    stdout_str = stdout.decode().strip() if stdout else ""
    stderr_str = stderr.decode().strip() if stderr else ""

    if proc.returncode != 0:
        raise GitError(
            f"Git command failed (exit {proc.returncode}): {' '.join(cmd)}\n{stderr_str}",
            stderr=stderr_str,
        )

    return stdout_str


async def clone_repo(
    repo_url: str,
    local_path: str | Path,
    branch: str = "main",
    shallow: bool = True,
) -> str:
    """
    Clone a repository.

    Returns the stdout output of the clone command.
    """
    _validate_repo_url(repo_url)
    _validate_branch(branch)
    args = ["clone"]
    if shallow:
        args.extend(["--depth", "1"])
    # "--" separates options from positional args so a crafted URL/branch can't
    # be reinterpreted as a git option.
    args.extend(["--branch", branch, "--", repo_url, str(local_path)])

    return await _run_git(*args, timeout=600)


async def pull_repo(
    local_path: str | Path,
    strategy: str = "ff-only",
) -> str:
    """Pull latest changes from remote.

    strategy:
        "ff-only" — fast-forward only (default, safest)
        "rebase"  — rebase local commits on top of remote
        "merge"   — create a merge commit
    """
    if strategy == "rebase":
        return await _run_git("pull", "--rebase", cwd=local_path)
    elif strategy == "merge":
        return await _run_git("pull", "--no-rebase", cwd=local_path)
    else:
        return await _run_git("pull", "--ff-only", cwd=local_path)


async def reset_to_remote(local_path: str | Path) -> str:
    """Hard reset the current branch to match the remote.

    Fetches latest from origin, then resets HEAD to origin/<branch>.
    Discards all local changes and commits.
    """
    await _run_git("fetch", "origin", cwd=local_path)
    branch = await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=local_path)
    return await _run_git("reset", "--hard", f"origin/{branch}", cwd=local_path)


async def checkout_branch(local_path: str | Path, branch: str) -> str:
    """Switch to a different branch."""
    _validate_branch(branch)
    # Fetch first to ensure we have the branch
    await _run_git("fetch", "origin", branch, cwd=local_path)
    return await _run_git("checkout", branch, cwd=local_path)


async def get_repo_status(local_path: str | Path) -> dict:
    """
    Get repository status.

    Returns dict with: branch, clean, last_commit_hash, last_commit_message
    """
    branch = await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=local_path)
    status = await _run_git("status", "--porcelain", cwd=local_path)
    clean = len(status) == 0

    log = await _run_git(
        "log", "-1", "--format=%H%n%s", cwd=local_path
    )
    lines = log.split("\n", 1)
    commit_hash = lines[0] if lines else ""
    commit_message = lines[1] if len(lines) > 1 else ""

    return {
        "branch": branch,
        "clean": clean,
        "last_commit_hash": commit_hash,
        "last_commit_message": commit_message,
    }


async def get_branches(local_path: str | Path) -> list[str]:
    """List remote branches."""
    try:
        await _run_git("fetch", "--prune", cwd=local_path, timeout=60)
    except GitError:
        logger.warning("Failed to fetch, listing cached remote branches")

    output = await _run_git("branch", "-r", cwd=local_path)
    branches = []
    for line in output.split("\n"):
        line = line.strip()
        if line and "->" not in line:
            # Strip "origin/" prefix
            if line.startswith("origin/"):
                line = line[len("origin/"):]
            branches.append(line)
    return branches
