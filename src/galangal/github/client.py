"""
GitHub CLI (gh) wrapper with authentication and repository verification.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass

from galangal.exceptions import GalangalError


class GitHubError(GalangalError):
    """Raised when GitHub operations fail."""

    pass


@dataclass
class GitHubCheckResult:
    """Result of GitHub setup verification."""

    gh_installed: bool
    gh_version: str | None
    authenticated: bool
    auth_user: str | None
    auth_scopes: list[str] | None
    repo_accessible: bool
    repo_name: str | None
    errors: list[str]

    @property
    def is_ready(self) -> bool:
        """Check if GitHub integration is fully ready."""
        return self.gh_installed and self.authenticated and self.repo_accessible


class GitHubClient:
    """
    Wrapper around the GitHub CLI (gh) for repository operations.

    Uses the gh CLI for all GitHub operations, piggybacking on the user's
    existing authentication rather than managing tokens directly.
    """

    def __init__(self):
        self._gh_path: str | None = None
        self._repo_name: str | None = None

    @property
    def gh_path(self) -> str | None:
        """Get path to gh executable, cached."""
        if self._gh_path is None:
            self._gh_path = shutil.which("gh")
        return self._gh_path

    def _run_gh(
        self,
        args: list[str],
        timeout: int = 30,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """
        Run a gh CLI command.

        Args:
            args: Arguments to pass to gh (e.g., ["issue", "list"])
            timeout: Command timeout in seconds
            check: If True, raise GitHubError on non-zero exit

        Returns:
            Tuple of (exit_code, stdout, stderr)

        Raises:
            GitHubError: If gh is not installed or command fails (when check=True)
        """
        if not self.gh_path:
            raise GitHubError("GitHub CLI (gh) is not installed")

        try:
            result = subprocess.run(
                [self.gh_path] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if check and result.returncode != 0:
                raise GitHubError(f"gh command failed: {result.stderr or result.stdout}")
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            raise GitHubError(f"gh command timed out after {timeout}s")
        except FileNotFoundError:
            raise GitHubError("GitHub CLI (gh) is not installed")

    def check_installation(self) -> tuple[bool, str | None]:
        """
        Check if gh CLI is installed.

        Returns:
            Tuple of (is_installed, version_string)
        """
        if not self.gh_path:
            return False, None

        try:
            code, out, _ = self._run_gh(["--version"], check=False)
            if code == 0:
                # Parse version from "gh version X.Y.Z (YYYY-MM-DD)"
                version = out.strip().split("\n")[0]
                return True, version
        except GitHubError:
            pass

        return False, None

    def check_auth(self) -> tuple[bool, str | None, list[str] | None]:
        """
        Check if user is authenticated with gh.

        Returns:
            Tuple of (is_authenticated, username, scopes)
        """
        try:
            code, out, _ = self._run_gh(
                ["auth", "status", "--show-token"],
                check=False,
            )

            if code != 0:
                return False, None, None

            # Parse auth status output
            username = None
            scopes = []

            for line in out.split("\n"):
                line = line.strip()
                if "Logged in to" in line and "as" in line:
                    # "Logged in to github.com as username"
                    parts = line.split(" as ")
                    if len(parts) >= 2:
                        username = parts[-1].strip().rstrip(")")
                elif "Token scopes:" in line:
                    # "Token scopes: 'repo', 'read:org'"
                    scope_part = line.split(":", 1)[-1].strip()
                    scopes = [s.strip().strip("'\"") for s in scope_part.split(",")]

            return True, username, scopes

        except GitHubError:
            return False, None, None

    def check_repo_access(self) -> tuple[bool, str | None]:
        """
        Check if current directory is a GitHub repository and we have access.

        Returns:
            Tuple of (has_access, repo_name)
        """
        try:
            # Get repo name from gh
            code, out, _ = self._run_gh(
                ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                check=False,
            )

            if code == 0 and out.strip():
                repo_name = out.strip()
                self._repo_name = repo_name
                return True, repo_name

            return False, None

        except GitHubError:
            return False, None

    def get_repo_name(self) -> str | None:
        """Get the current repository name (owner/repo format)."""
        if self._repo_name is None:
            _, self._repo_name = self.check_repo_access()
        return self._repo_name

    def check_setup(self) -> GitHubCheckResult:
        """
        Perform a comprehensive check of GitHub setup.

        Returns:
            GitHubCheckResult with all check details
        """
        errors = []

        # Check installation
        gh_installed, gh_version = self.check_installation()
        if not gh_installed:
            errors.append("GitHub CLI (gh) is not installed. Install from: https://cli.github.com")

        # Check authentication
        authenticated = False
        auth_user = None
        auth_scopes = None
        if gh_installed:
            authenticated, auth_user, auth_scopes = self.check_auth()
            if not authenticated:
                errors.append("Not authenticated. Run: gh auth login")

        # Check repository access
        repo_accessible = False
        repo_name = None
        if authenticated:
            repo_accessible, repo_name = self.check_repo_access()
            if not repo_accessible:
                errors.append(
                    "Cannot access repository. Ensure you're in a git repo "
                    "with a GitHub remote and have push access."
                )

        return GitHubCheckResult(
            gh_installed=gh_installed,
            gh_version=gh_version,
            authenticated=authenticated,
            auth_user=auth_user,
            auth_scopes=auth_scopes,
            repo_accessible=repo_accessible,
            repo_name=repo_name,
            errors=errors,
        )

    def run_json_command(self, args: list[str], timeout: int = 30) -> dict | list | None:
        """
        Run a gh command that returns JSON.

        Args:
            args: Arguments to pass to gh
            timeout: Command timeout in seconds

        Returns:
            Parsed JSON response, or None on error
        """
        _, out, _ = self._run_gh(args, timeout=timeout)
        if out.strip():
            return json.loads(out)
        return None

    def add_issue_comment(self, issue_number: int, body: str) -> bool:
        """
        Add a comment to an issue.

        Args:
            issue_number: Issue number
            body: Comment body

        Returns:
            True if successful
        """
        try:
            self._run_gh(["issue", "comment", str(issue_number), "--body", body])
            return True
        except GitHubError:
            return False

    def add_issue_label(self, issue_number: int, label: str) -> bool:
        """
        Add a label to an issue.

        Args:
            issue_number: Issue number
            label: Label name

        Returns:
            True if successful
        """
        try:
            self._run_gh(["issue", "edit", str(issue_number), "--add-label", label])
            return True
        except GitHubError:
            return False

    def remove_issue_label(self, issue_number: int, label: str) -> bool:
        """
        Remove a label from an issue.

        Args:
            issue_number: Issue number
            label: Label name

        Returns:
            True if successful
        """
        try:
            self._run_gh(["issue", "edit", str(issue_number), "--remove-label", label])
            return True
        except GitHubError:
            return False

    def get_issue_state(self, issue_number: int) -> str | None:
        """
        Get the current state of an issue.

        Args:
            issue_number: Issue number

        Returns:
            "open", "closed", or None if not found
        """
        try:
            data = self.run_json_command(
                ["issue", "view", str(issue_number), "--json", "state"]
            )
            if data and "state" in data:
                return data["state"].lower()
        except GitHubError:
            pass
        return None

    def list_labels(self) -> list[dict] | None:
        """
        List all labels in the repository.

        Returns:
            List of label dicts with 'name', 'color', 'description' keys,
            or None on error
        """
        try:
            return self.run_json_command(
                ["label", "list", "--json", "name,color,description"]
            )
        except GitHubError:
            return None

    def label_exists(self, name: str) -> bool:
        """
        Check if a label exists in the repository.

        Args:
            name: Label name to check

        Returns:
            True if label exists
        """
        labels = self.list_labels()
        if labels:
            return any(label["name"].lower() == name.lower() for label in labels)
        return False

    def create_label(
        self,
        name: str,
        color: str = "CCCCCC",
        description: str = "",
    ) -> bool:
        """
        Create a new label in the repository.

        Args:
            name: Label name
            color: Hex color without # (e.g., "7C3AED")
            description: Label description

        Returns:
            True if successful
        """
        try:
            args = ["label", "create", name, "--color", color]
            if description:
                args.extend(["--description", description])
            self._run_gh(args)
            return True
        except GitHubError:
            return False

    def create_label_if_missing(
        self,
        name: str,
        color: str = "CCCCCC",
        description: str = "",
    ) -> tuple[bool, bool]:
        """
        Create a label if it doesn't already exist.

        Args:
            name: Label name
            color: Hex color without # (e.g., "7C3AED")
            description: Label description

        Returns:
            Tuple of (success, was_created). success is True if label exists
            (whether created or already existed). was_created is True only
            if the label was newly created.
        """
        if self.label_exists(name):
            return True, False

        success = self.create_label(name, color, description)
        return success, success
