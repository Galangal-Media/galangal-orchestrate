"""
GitHub integration for Galangal Orchestrate.

Provides:
- gh CLI wrapper with auth verification
- Issue listing and filtering by label
- PR creation with issue linking
"""

from galangal.github.client import GitHubClient
from galangal.github.issues import GitHubIssue, list_issues

__all__ = ["GitHubClient", "GitHubIssue", "list_issues"]
