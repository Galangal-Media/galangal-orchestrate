"""Tests for baseline error diffing (fail only on errors new since the base commit)."""

import subprocess

from galangal.validation.baseline import compute_baseline_errors, normalize_error_lines


def test_normalize_strips_path_and_linecol():
    n = normalize_error_lines("/abs/proj/foo.py:12:5 - error: bad attr 'x'", ["/abs/proj"])
    assert n == {"foo.py:N - error: bad attr 'x'"}


def test_normalize_matches_across_line_shift():
    # Same error at different line numbers should normalize to the same key.
    a = normalize_error_lines("foo.py:10:3 - error: boom", [])
    b = normalize_error_lines("foo.py:42:3 - error: boom", [])
    assert a == b


def _make_repo(tmp_path):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t.co")
    git("config", "user.name", "t")
    (tmp_path / "code.py").write_text("# BUG pre-existing\nx = 1\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    return base, git


def test_baseline_isolates_new_errors(tmp_path):
    base, _ = _make_repo(tmp_path)
    # current tree introduces a NEW "BUG" line on top of the pre-existing one
    (tmp_path / "code.py").write_text("# BUG pre-existing\nx = 1\n# BUG new one\n")

    cmd = "grep -n BUG code.py"
    baseline = compute_baseline_errors(cmd, shell=True, base_sha=base, project_root=tmp_path, timeout=30)
    assert baseline is not None and len(baseline) == 1  # only the pre-existing BUG

    cur = subprocess.run(cmd, shell=True, cwd=tmp_path, capture_output=True, text=True)
    current = normalize_error_lines(cur.stdout + cur.stderr, [str(tmp_path)])
    new = current - baseline
    assert len(new) == 1
    assert any("new one" in line for line in new)
    assert not any("pre-existing" in line for line in new)  # pre-existing filtered out


def test_baseline_is_cached(tmp_path):
    base, _ = _make_repo(tmp_path)
    cmd = "grep -n BUG code.py"
    first = compute_baseline_errors(cmd, shell=True, base_sha=base, project_root=tmp_path, timeout=30)
    # Cache file written under .galangal/baseline_cache
    assert (tmp_path / ".galangal" / "baseline_cache").exists()
    second = compute_baseline_errors(cmd, shell=True, base_sha=base, project_root=tmp_path, timeout=30)
    assert first == second


def test_compute_returns_none_on_bad_sha(tmp_path):
    _make_repo(tmp_path)
    out = compute_baseline_errors(
        "grep -n BUG code.py", shell=True, base_sha="deadbeef" * 5, project_root=tmp_path, timeout=30
    )
    assert out is None  # worktree add fails -> graceful fallback


def test_runner_verdict_passes_preexisting_fails_new(tmp_path):
    # A baseline_diff command that always exits non-zero: it must PASS when only
    # pre-existing errors are present, and FAIL once a new error appears.
    from galangal.config.schema import ValidationCommand
    from galangal.validation.runner import ValidationRunner

    base, _ = _make_repo(tmp_path)
    runner = ValidationRunner.__new__(ValidationRunner)  # bypass __init__ (get_config)
    runner.project_root = tmp_path
    runner._base_sha = base

    cmd = "grep -n BUG code.py; exit 1"  # always non-zero, like a linter with findings
    cfg = ValidationCommand(name="lint", command=cmd, baseline_diff=True)

    # current == base (only the pre-existing BUG) -> PASS despite exit 1
    cur = subprocess.run(cmd, shell=True, cwd=tmp_path, capture_output=True, text=True)
    v = runner._apply_baseline_diff(cfg, cmd, True, cur, base, 30)
    assert v is not None and v.success is True

    # introduce a new error -> FAIL
    (tmp_path / "code.py").write_text("# BUG pre-existing\n# BUG new\n")
    cur2 = subprocess.run(cmd, shell=True, cwd=tmp_path, capture_output=True, text=True)
    v2 = runner._apply_baseline_diff(cfg, cmd, True, cur2, base, 30)
    assert v2 is not None and v2.success is False
    assert "new" in v2.output.lower()
