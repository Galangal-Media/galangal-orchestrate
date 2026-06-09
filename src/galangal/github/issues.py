"""
GitHub issue listing and parsing.
"""

from dataclasses import dataclass
from typing import ClassVar

from galangal.config.loader import get_config
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

    # Resolution order when an issue carries labels for several task types. The
    # most urgent / specific type wins, so e.g. an issue tagged both "hotfix" and
    # "feature" deterministically resolves to hotfix regardless of label order.
    _TYPE_PRIORITY: ClassVar[tuple[str, ...]] = (
        "hotfix",
        "bug_fix",
        "refactor",
        "feature",
        "chore",
        "docs",
    )

    # Hardcoded fallback used when config is unavailable.
    _DEFAULT_LABELS: ClassVar[dict[str, set[str]]] = {
        "bug_fix": {"bug", "bugfix"},
        "feature": {"enhancement", "feature"},
        "docs": {"documentation", "docs"},
        "refactor": {"refactor"},
        "chore": {"chore", "maintenance"},
        "hotfix": {"hotfix", "critical"},
    }

    def get_task_type_hint(self) -> str | None:
        """
        Infer task type from issue labels using config-based mapping.

        Resolution is by fixed priority (see ``_TYPE_PRIORITY``), not label
        order, so the result is deterministic when an issue matches more than one
        task type.

        Returns:
            Suggested task type or None if no match
        """
        from galangal.config.loader import get_config

        label_lower = {lbl.lower() for lbl in self.labels}

        # Build a {task_type: set(labels)} map from config, falling back to
        # hardcoded defaults if config is unavailable.
        try:
            mapping = get_config().github.label_mapping
            type_labels = {
                "bug_fix": {lbl.lower() for lbl in mapping.bug},
                "feature": {lbl.lower() for lbl in mapping.feature},
                "docs": {lbl.lower() for lbl in mapping.docs},
                "refactor": {lbl.lower() for lbl in mapping.refactor},
                "chore": {lbl.lower() for lbl in mapping.chore},
                "hotfix": {lbl.lower() for lbl in mapping.hotfix},
            }
        except Exception:
            type_labels = self._DEFAULT_LABELS

        for task_type in self._TYPE_PRIORITY:
            if label_lower & type_labels.get(task_type, set()):
                return task_type

        return None


def list_issues(
    label: str = GALANGAL_LABEL,
    state: str = "open",
    limit: int = 200,
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

    data = client.run_json_command(
        [
            "issue",
            "list",
            "--label",
            label,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,title,body,labels,state,url,author",
        ]
    )

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
        data = client.run_json_command(
            [
                "issue",
                "view",
                str(issue_number),
                "--json",
                "number,title,body,labels,state,url,author",
            ]
        )

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


def restore_issue_to_pickup(issue_number: int) -> bool:
    """
    Return an issue to the pickup queue after a task is abandoned or fails.

    Inverse of :func:`mark_issue_in_progress`: removes "in-progress" and re-adds
    the "galangal" pickup label so the issue is visible again to `galangal github
    issues`. Safe to call when the labels are already in that state.

    Args:
        issue_number: The issue number

    Returns:
        True if successful
    """
    client = GitHubClient()
    success1 = client.remove_issue_label(issue_number, "in-progress")
    success2 = client.add_issue_label(issue_number, GALANGAL_LABEL)
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


@dataclass
class IssueTaskData:
    """Data extracted from a GitHub issue for task creation."""

    issue_number: int
    description: str
    task_type_hint: str | None
    github_repo: str | None
    screenshots: list[str]
    issue_body: str  # Raw body for later screenshot download
    task_name: str | None = None  # Generated task name (set after creation)


def prepare_issue_for_task(
    issue: GitHubIssue,
    repo_name: str | None = None,
) -> IssueTaskData:
    """
    Extract task creation data from a GitHub issue.

    This consolidates all the issue-to-task conversion logic:
    - Forms description from title + body
    - Infers task type from labels
    - Identifies screenshots for later download

    Args:
        issue: The GitHub issue to process
        repo_name: Optional repo name (owner/repo), fetched if not provided

    Returns:
        IssueTaskData with all info needed for task creation

    Note:
        Screenshots are NOT downloaded here - the task directory needs to
        exist first. Use download_issue_screenshots() after task creation.
    """
    # Get repo name if not provided
    if not repo_name:
        client = GitHubClient()
        repo_name = client.get_repo_name()

    # Form description from title and body
    description = f"{issue.title}\n\n{issue.body}"

    # Optionally append the comment thread — clarifications, repro steps, and
    # decisions usually live there, not in the original body. The same combined
    # text is stored as ``issue_body`` so screenshots posted in comments are
    # picked up by download_issue_screenshots() too.
    comments_md = _fetch_and_format_comments(issue.number)
    if comments_md:
        description = f"{description}\n\n{comments_md}"

    screenshot_source = issue.body
    if comments_md:
        screenshot_source = f"{issue.body}\n\n{comments_md}"

    return IssueTaskData(
        issue_number=issue.number,
        description=description,
        task_type_hint=issue.get_task_type_hint(),
        github_repo=repo_name,
        screenshots=[],  # Populated after task dir exists
        issue_body=screenshot_source,
    )


def _fetch_and_format_comments(issue_number: int) -> str:
    """Fetch and render an issue's comment thread as markdown.

    Returns an empty string when comment ingestion is disabled, there are no
    comments, or the fetch fails (all non-fatal — the task proceeds without
    comment context).
    """
    try:
        config = get_config()
        if not config.github.include_issue_comments:
            return ""
        max_comments = config.github.max_issue_comments
    except Exception:
        # Config unavailable: default to including a bounded number of comments.
        max_comments = 20

    try:
        comments = GitHubClient().get_issue_comments(issue_number)
    except Exception:
        return ""

    if not comments:
        return ""

    # Keep the most recent N to bound prompt size, but render oldest-first so the
    # discussion reads in chronological order.
    if max_comments > 0 and len(comments) > max_comments:
        comments = comments[-max_comments:]

    lines = ["## Issue Discussion (comments)"]
    for c in comments:
        author = (c.get("author") or {}).get("login", "unknown")
        when = c.get("createdAt", "")
        body = (c.get("body") or "").strip()
        if not body:
            continue
        header = f"**@{author}**" + (f" ({when})" if when else "")
        lines.append(f"\n{header}:\n{body}")

    # Only a header means every comment was empty.
    return "\n".join(lines) if len(lines) > 1 else ""


def download_issue_screenshots(
    issue_body: str,
    task_dir,
) -> list[str]:
    """
    Download screenshots from an issue body to the task directory.

    Args:
        issue_body: The raw issue body markdown
        task_dir: Path to the task directory (will create screenshots/ subdir)

    Returns:
        List of local file paths to downloaded screenshots
    """
    from pathlib import Path

    from galangal.github.images import download_issue_images

    task_dir = Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)

    return download_issue_images(issue_body, task_dir)
