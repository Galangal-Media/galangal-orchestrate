"""
GitHub issue listing and parsing.
"""

from dataclasses import dataclass

from galangal.github.client import GitHubClient, GitHubError

# Default label for galangal-managed issues
GALANGAL_LABEL = "galangal"


@dataclass
class GitHubIssue:
    """Representation of a GitHub issue."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str
    url: str
    author: str

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubIssue":
        """Create from gh JSON output."""
        return cls(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            labels=[label["name"] for label in data.get("labels", [])],
            state=data.get("state", "open").lower(),
            url=data.get("url", ""),
            author=data.get("author", {}).get("login", "unknown"),
        )

    def get_task_name_prefix(self) -> str:
        """Generate a task name prefix from the issue number."""
        return f"issue-{self.number}"

    def get_task_type_hint(self) -> str | None:
        """
        Infer task type from issue labels using config-based mapping.

        Returns:
            Suggested task type or None if no match
        """
        from galangal.config.loader import get_config

        label_lower = [lbl.lower() for lbl in self.labels]

        # Get label mapping from config
        try:
            config = get_config()
            mapping = config.github.label_mapping
        except Exception:
            # Fall back to defaults if config not available
            mapping = None

        if mapping:
            # Check each task type's labels
            for label in label_lower:
                if label in [lbl.lower() for lbl in mapping.bug]:
                    return "bug_fix"
                if label in [lbl.lower() for lbl in mapping.feature]:
                    return "feature"
                if label in [lbl.lower() for lbl in mapping.docs]:
                    return "docs"
                if label in [lbl.lower() for lbl in mapping.refactor]:
                    return "refactor"
                if label in [lbl.lower() for lbl in mapping.chore]:
                    return "chore"
                if label in [lbl.lower() for lbl in mapping.hotfix]:
                    return "hotfix"
        else:
            # Fallback to hardcoded defaults
            if "bug" in label_lower or "bugfix" in label_lower:
                return "bug_fix"
            if "enhancement" in label_lower or "feature" in label_lower:
                return "feature"
            if "documentation" in label_lower or "docs" in label_lower:
                return "docs"
            if "refactor" in label_lower:
                return "refactor"
            if "chore" in label_lower or "maintenance" in label_lower:
                return "chore"
            if "hotfix" in label_lower or "critical" in label_lower:
                return "hotfix"

        return None


def list_issues(
    label: str = GALANGAL_LABEL,
    state: str = "open",
    limit: int = 50,
) -> list[GitHubIssue]:
    """
    List issues from the current repository with the given label.

    Args:
        label: Label to filter by (default: "galangal")
        state: Issue state filter ("open", "closed", "all")
        limit: Maximum number of issues to return

    Returns:
        List of GitHubIssue objects

    Raises:
        GitHubError: If GitHub operations fail
    """
    client = GitHubClient()

    data = client.run_json_command([
        "issue", "list",
        "--label", label,
        "--state", state,
        "--limit", str(limit),
        "--json", "number,title,body,labels,state,url,author",
    ])

    if not data:
        return []

    return [GitHubIssue.from_dict(item) for item in data]


def get_issue(issue_number: int) -> GitHubIssue | None:
    """
    Get a single issue by number.

    Args:
        issue_number: The issue number

    Returns:
        GitHubIssue or None if not found
    """
    client = GitHubClient()

    try:
        data = client.run_json_command([
            "issue", "view",
            str(issue_number),
            "--json", "number,title,body,labels,state,url,author",
        ])

        if data:
            return GitHubIssue.from_dict(data)
    except GitHubError:
        pass

    return None


def is_issue_open(issue_number: int) -> bool | None:
    """
    Check if an issue is still open.

    Args:
        issue_number: The issue number

    Returns:
        True if open, False if closed, None if not found/error
    """
    client = GitHubClient()
    state = client.get_issue_state(issue_number)
    if state is None:
        return None
    return state == "open"


def mark_issue_in_progress(issue_number: int) -> bool:
    """
    Mark an issue as being worked on by galangal.

    Adds "in-progress" label and removes "galangal" label.

    Args:
        issue_number: The issue number

    Returns:
        True if successful
    """
    client = GitHubClient()
    success1 = client.add_issue_label(issue_number, "in-progress")
    success2 = client.remove_issue_label(issue_number, GALANGAL_LABEL)
    return success1 and success2


def mark_issue_pr_created(issue_number: int, pr_url: str) -> bool:
    """
    Mark an issue as having a PR created.

    Adds a comment with the PR link.

    Args:
        issue_number: The issue number
        pr_url: URL to the created PR

    Returns:
        True if successful
    """
    client = GitHubClient()
    comment = f"Pull request created: {pr_url}"
    return client.add_issue_comment(issue_number, comment)
