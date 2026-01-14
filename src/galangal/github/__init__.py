"""
GitHub integration for Galangal Orchestrate.

Provides:
- gh CLI wrapper with auth verification
- Issue listing and filtering by label
- PR creation with issue linking
- Image extraction and download from issue bodies
"""

from galangal.github.client import GitHubClient
from galangal.github.images import download_issue_images, extract_image_urls
from galangal.github.issues import GitHubIssue, list_issues

__all__ = [
    "GitHubClient",
    "GitHubIssue",
    "list_issues",
    "download_issue_images",
    "extract_image_urls",
]
