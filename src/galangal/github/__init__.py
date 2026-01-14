"""
GitHub integration for Galangal Orchestrate.

Provides:
- gh CLI wrapper with auth verification
- Issue listing and filtering by label
- PR creation with issue linking
- Image extraction and download from issue bodies
"""

from galangal.github.client import GitHubClient, ensure_github_ready
from galangal.github.images import download_issue_images, extract_image_urls
from galangal.github.issues import (
    GitHubIssue,
    IssueTaskData,
    download_issue_screenshots,
    list_issues,
    prepare_issue_for_task,
)

__all__ = [
    "GitHubClient",
    "GitHubIssue",
    "IssueTaskData",
    "download_issue_images",
    "download_issue_screenshots",
    "ensure_github_ready",
    "extract_image_urls",
    "list_issues",
    "prepare_issue_for_task",
]
