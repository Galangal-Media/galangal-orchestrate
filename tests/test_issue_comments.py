"""Tests for GitHub issue comment ingestion into task context."""

from unittest.mock import patch

from galangal.config.schema import GalangalConfig, GitHubConfig
from galangal.github.issues import GitHubIssue, prepare_issue_for_task


def _issue() -> GitHubIssue:
    return GitHubIssue(
        number=7,
        title="Export is wrong",
        body="The CSV export drops the last row.",
        labels=["bug"],
        state="open",
        url="",
        author="alice",
    )


_COMMENTS = [
    {"author": {"login": "bob"}, "createdAt": "2026-01-01", "body": "Can you share a repro?"},
    {"author": {"login": "alice"}, "createdAt": "2026-01-02", "body": "Happens with >1000 rows."},
    {"author": {"login": "carol"}, "createdAt": "2026-01-03", "body": ""},  # empty -> skipped
]


def test_comments_appended_to_description():
    cfg = GalangalConfig(github=GitHubConfig(include_issue_comments=True))
    with (
        patch("galangal.github.issues.get_config", return_value=cfg),
        patch(
            "galangal.github.issues.GitHubClient.get_issue_comments",
            return_value=_COMMENTS,
        ),
    ):
        data = prepare_issue_for_task(_issue(), repo_name="o/r")

    assert "Issue Discussion (comments)" in data.description
    assert "Happens with >1000 rows." in data.description
    assert "**@bob**" in data.description
    # Empty comment body is skipped.
    assert "**@carol**" not in data.description
    # Comments also feed the screenshot source so comment images are downloaded.
    assert "Happens with >1000 rows." in data.issue_body


def test_comments_disabled_by_config():
    cfg = GalangalConfig(github=GitHubConfig(include_issue_comments=False))
    with (
        patch("galangal.github.issues.get_config", return_value=cfg),
        patch(
            "galangal.github.issues.GitHubClient.get_issue_comments",
            return_value=_COMMENTS,
        ) as mock_fetch,
    ):
        data = prepare_issue_for_task(_issue(), repo_name="o/r")

    assert "Issue Discussion" not in data.description
    mock_fetch.assert_not_called()


def test_max_issue_comments_truncates_to_most_recent():
    cfg = GalangalConfig(
        github=GitHubConfig(include_issue_comments=True, max_issue_comments=2)
    )
    with (
        patch("galangal.github.issues.get_config", return_value=cfg),
        patch(
            "galangal.github.issues.GitHubClient.get_issue_comments",
            return_value=_COMMENTS,
        ),
    ):
        data = prepare_issue_for_task(_issue(), repo_name="o/r")

    # Keeps the most recent 2 raw comments (alice + carol); carol's is empty and
    # is dropped at render time, so only alice's survives and bob's is excluded.
    assert "Happens with >1000 rows." in data.description
    assert "Can you share a repro?" not in data.description
