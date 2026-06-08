"""Tests for squash_to_base ancestry guard and squash mechanics."""

import subprocess

import pytest

from galangal.core.git_utils import get_current_head, squash_to_base


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.co")
    _git(r, "config", "user.name", "t")
    return r


def _commit(repo, fname, content, msg):
    (repo / fname).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return get_current_head(cwd=repo)


def test_squash_collapses_commits_on_top_of_base(repo):
    base = _commit(repo, "a.txt", "1", "base")
    _commit(repo, "b.txt", "2", "wip1")
    _commit(repo, "c.txt", "3", "wip2")

    assert squash_to_base(base, "squashed", cwd=repo) is True

    # One commit on top of base, with all files present.
    log = subprocess.run(
        ["git", "log", "--oneline", f"{base}..HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip().splitlines()
    assert len(log) == 1
    for f in ("a.txt", "b.txt", "c.txt"):
        assert (repo / f).exists()


def test_squash_rejects_non_ancestor_base(repo):
    _commit(repo, "a.txt", "1", "base")
    _commit(repo, "b.txt", "2", "wip")
    head_before = get_current_head(cwd=repo)

    # A fabricated/unrelated SHA is not an ancestor -> must refuse, not corrupt.
    fake_sha = "0" * 40
    assert squash_to_base(fake_sha, "squashed", cwd=repo) is False
    assert get_current_head(cwd=repo) == head_before  # history untouched


def test_squash_rejects_head_equal_base(repo):
    base = _commit(repo, "a.txt", "1", "base")
    # No commits on top of base.
    assert squash_to_base(base, "squashed", cwd=repo) is False
