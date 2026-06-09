"""Baseline error diffing for validation commands.

Real repositories carry pre-existing lint/type-check errors, so gating a command
purely on its exit code forces teams to disable the check entirely — and then a
genuine *new* error introduced by a task (e.g. a hallucinated SDK attribute that a
type checker flags) slips straight through.

This module computes a command's error set at the task's base commit (once, cached)
so the runner can report only the errors introduced *since* the base. The baseline
is produced from a transient ``git worktree`` checked out at the base SHA.

Caveat: the baseline command runs with its cwd set to the base worktree. Tools that
resolve dependencies from the working tree (e.g. a local ``node_modules`` or
``.venv``) should be globally installed or reference their environment by absolute
path, so the base run sees the same toolchain as the current run.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Collapse ":line" / ":line:col" so an error that merely shifted lines between the
# base and current tree still matches its baseline counterpart.
_LINECOL_RE = re.compile(r":\d+(?::\d+)?")


def normalize_error_lines(text: str, strip_prefixes: list[str]) -> set[str]:
    """Normalize tool output into a comparable set of error lines.

    Strips the given path prefixes (so base-worktree and current paths line up) and
    collapses line/column numbers. Heuristic but tool-agnostic (pyright, mypy, ruff,
    tsc, eslint, …): a genuinely new error — new message or new file — won't match
    any baseline line, while a pre-existing one that moved lines still does.
    """
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        for prefix in strip_prefixes:
            if prefix:
                line = line.replace(prefix, "")
        line = line.lstrip("./ ")
        line = _LINECOL_RE.sub(":N", line)
        out.add(line)
    return out


def _cache_path(project_root: Path, base_sha: str, command_key: str) -> Path:
    h = hashlib.sha256(command_key.encode()).hexdigest()[:12]
    return project_root / ".galangal" / "baseline_cache" / f"{base_sha[:12]}-{h}.txt"


def compute_baseline_errors(
    command: str | list[str],
    *,
    shell: bool,
    base_sha: str,
    project_root: Path,
    timeout: int,
) -> set[str] | None:
    """Return the normalized error set for ``command`` at ``base_sha``.

    Cached per (base_sha, command) under ``.galangal/baseline_cache``. Returns None
    if the baseline could not be produced (no git, bad SHA, worktree failure) so the
    caller can fall back to plain gating.
    """
    command_key = command if isinstance(command, str) else " ".join(command)
    cache = _cache_path(project_root, base_sha, command_key)
    if cache.exists():
        try:
            return set(cache.read_text(encoding="utf-8").splitlines())
        except OSError:
            pass

    errors = _run_in_base_worktree(
        command, shell=shell, base_sha=base_sha, project_root=project_root, timeout=timeout
    )
    if errors is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text("\n".join(sorted(errors)), encoding="utf-8")
        except OSError:
            pass
    return errors


def _run_in_base_worktree(
    command: str | list[str],
    *,
    shell: bool,
    base_sha: str,
    project_root: Path,
    timeout: int,
) -> set[str] | None:
    with tempfile.TemporaryDirectory(prefix="galangal-baseline-") as tmp:
        wt = Path(tmp) / "wt"
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(wt), base_sha],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if add.returncode != 0:
            logger.warning("baseline_diff: could not create worktree at %s: %s", base_sha, add.stderr.strip())
            return None
        try:
            res = subprocess.run(
                command,
                shell=shell,
                cwd=wt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return normalize_error_lines(res.stdout + res.stderr, [str(wt), str(project_root)])
        except Exception as e:  # noqa: BLE001 - best-effort baseline
            logger.warning("baseline_diff: base command failed: %s", e)
            return None
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
