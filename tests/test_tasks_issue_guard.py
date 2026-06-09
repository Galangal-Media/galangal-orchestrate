"""Tests for the duplicate-issue guard in create_task_from_issue."""

from unittest.mock import patch

from galangal.core.tasks import create_task_from_issue
from galangal.github.issues import GitHubIssue


def _issue(number: int = 42) -> GitHubIssue:
    return GitHubIssue(
        number=number,
        title="Something broke",
        body="repro steps",
        labels=["bug"],
        state="open",
        url="https://example/issues/42",
        author="octocat",
    )


def test_refuses_duplicate_task_for_issue():
    """If an active task already exists for the issue, refuse and point to it."""
    with patch(
        "galangal.core.tasks.find_active_task_for_issue",
        return_value="issue-42-existing",
    ):
        # is_on_base_branch must never be reached — the guard returns first.
        with patch("galangal.core.tasks.is_on_base_branch") as mock_branch:
            result = create_task_from_issue(_issue())

    assert result.success is False
    assert result.task_name == "issue-42-existing"
    assert "already has an active task" in result.message
    mock_branch.assert_not_called()


def test_resume_with_same_override_not_blocked_by_guard():
    """Passing the existing task's name as the override is a resume, not a dup."""
    with patch(
        "galangal.core.tasks.find_active_task_for_issue",
        return_value="issue-42-existing",
    ):
        # The guard should fall through; stop the flow right after at branch check
        # so we don't exercise the whole creation pipeline.
        with patch(
            "galangal.core.tasks.is_on_base_branch",
            side_effect=RuntimeError("reached branch check"),
        ):
            try:
                create_task_from_issue(
                    _issue(), task_name_override="issue-42-existing"
                )
            except RuntimeError as e:
                assert "reached branch check" in str(e)
            else:
                raise AssertionError("guard should not have short-circuited")
