"""
galangal github - GitHub integration commands.
"""

import argparse
import platform

from galangal.ui.console import console, print_error, print_info, print_success, print_warning

GH_INSTALL_INSTRUCTIONS = """
GitHub CLI (gh) is required for GitHub integration.

Installation instructions:

  macOS:
    brew install gh

  Windows:
    winget install GitHub.cli
    # or download from https://github.com/cli/cli/releases

  Linux (Debian/Ubuntu):
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update && sudo apt install gh

  Linux (Fedora):
    sudo dnf install gh

  Linux (Arch):
    sudo pacman -S github-cli

After installation, authenticate with:
    gh auth login

For more info: https://cli.github.com
"""


def _get_platform_install_hint() -> str:
    """Get platform-specific installation hint."""
    system = platform.system().lower()
    if system == "darwin":
        return "brew install gh"
    elif system == "windows":
        return "winget install GitHub.cli"
    elif system == "linux":
        return "See https://cli.github.com for Linux install instructions"
    return "See https://cli.github.com"


def cmd_github_setup(args: argparse.Namespace) -> int:
    """Set up GitHub integration by creating required labels."""
    from galangal.config.loader import get_config
    from galangal.github.client import GitHubClient

    console.print("\n[bold]GitHub Integration Setup[/bold]\n")

    client = GitHubClient()

    # Step 1: Check if gh is installed
    gh_installed, gh_version = client.check_installation()
    if not gh_installed:
        print_error("GitHub CLI (gh) is not installed")
        console.print(f"\n[dim]Quick install: {_get_platform_install_hint()}[/dim]")
        if getattr(args, "help_install", False):
            console.print(GH_INSTALL_INSTRUCTIONS)
        else:
            console.print("\n[dim]Run 'galangal github setup --help-install' for detailed instructions[/dim]")
        return 1

    print_success(f"GitHub CLI installed: {gh_version}")

    # Step 2: Check authentication
    authenticated, auth_user, _ = client.check_auth()
    if not authenticated:
        print_error("Not authenticated with GitHub")
        console.print("\n[dim]Run: gh auth login[/dim]")
        return 1

    print_success(f"Authenticated as: {auth_user}")

    # Step 3: Check repository access
    repo_accessible, repo_name = client.check_repo_access()
    if not repo_accessible:
        print_error("Cannot access repository")
        console.print("\n[dim]Ensure you're in a git repo with a GitHub remote[/dim]")
        return 1

    print_success(f"Repository: {repo_name}")

    console.print("\n[dim]─────────────────────────────────────[/dim]")
    console.print("\n[bold]Creating labels...[/bold]\n")

    # Step 4: Create required labels
    config = get_config()
    github_config = config.github

    labels_to_create = [
        (
            github_config.pickup_label,
            github_config.label_colors.get(github_config.pickup_label, "7C3AED"),
            "Issues for galangal to work on",
        ),
        (
            github_config.in_progress_label,
            github_config.label_colors.get(github_config.in_progress_label, "FCD34D"),
            "Issue is being worked on by galangal",
        ),
    ]

    created_count = 0
    for label_name, color, description in labels_to_create:
        success, was_created = client.create_label_if_missing(
            label_name, color, description
        )
        if success:
            if was_created:
                print_success(f"Created label: {label_name}")
                created_count += 1
            else:
                print_info(f"Label already exists: {label_name}")
        else:
            print_error(f"Failed to create label: {label_name}")

    # Step 5: Show summary and next steps
    console.print("\n[dim]─────────────────────────────────────[/dim]")
    console.print("\n[bold]Setup complete![/bold]\n")

    if created_count > 0:
        console.print(f"Created {created_count} new label(s).\n")

    console.print("[bold]How to use GitHub integration:[/bold]")
    console.print(f"  1. Add the '[cyan]{github_config.pickup_label}[/cyan]' label to issues you want galangal to work on")
    console.print("  2. Run '[cyan]galangal start[/cyan]' and select 'GitHub issue' as the task source")
    console.print("  3. Or run '[cyan]galangal github run[/cyan]' to process all labeled issues automatically")

    console.print("\n[bold]Label to task type mapping:[/bold]")
    mapping = github_config.label_mapping
    console.print(f"  bug_fix:  {', '.join(mapping.bug)}")
    console.print(f"  feature:  {', '.join(mapping.feature)}")
    console.print(f"  docs:     {', '.join(mapping.docs)}")
    console.print(f"  refactor: {', '.join(mapping.refactor)}")
    console.print(f"  chore:    {', '.join(mapping.chore)}")
    console.print(f"  hotfix:   {', '.join(mapping.hotfix)}")

    console.print("\n[dim]Customize mappings in .galangal/config.yaml under 'github.label_mapping'[/dim]")

    return 0


def cmd_github_check(args: argparse.Namespace) -> int:
    """Check GitHub CLI installation and repository access."""
    from galangal.github.client import GitHubClient

    console.print("\n[bold]GitHub Integration Check[/bold]\n")

    client = GitHubClient()
    result = client.check_setup()

    # Display results
    console.print("[dim]─────────────────────────────────────[/dim]")

    # 1. gh CLI installation
    if result.gh_installed:
        print_success(f"gh CLI installed: {result.gh_version}")
    else:
        print_error("gh CLI not installed")
        console.print("  [dim]Install from: https://cli.github.com[/dim]")

    # 2. Authentication
    if result.authenticated:
        print_success(f"Authenticated as: {result.auth_user}")
        if result.auth_scopes:
            console.print(f"  [dim]Scopes: {', '.join(result.auth_scopes)}[/dim]")
    elif result.gh_installed:
        print_error("Not authenticated")
        console.print("  [dim]Run: gh auth login[/dim]")

    # 3. Repository access
    if result.repo_accessible:
        print_success(f"Repository: {result.repo_name}")
    elif result.authenticated:
        print_error("Cannot access repository")
        console.print("  [dim]Ensure you're in a git repo with a GitHub remote[/dim]")

    console.print("[dim]─────────────────────────────────────[/dim]\n")

    # Summary
    if result.is_ready:
        print_success("GitHub integration is ready")
        return 0
    else:
        print_error("GitHub integration not ready")
        if result.errors:
            console.print("\n[bold]Issues to resolve:[/bold]")
            for error in result.errors:
                console.print(f"  • {error}")
        return 1


def cmd_github_issues(args: argparse.Namespace) -> int:
    """List GitHub issues with the galangal label."""
    from rich.table import Table

    from galangal.github.client import GitHubClient, GitHubError
    from galangal.github.issues import GALANGAL_LABEL, list_issues

    # First check setup
    client = GitHubClient()
    check = client.check_setup()

    if not check.is_ready:
        print_error("GitHub integration not ready. Run 'galangal github check' for details.")
        return 1

    label = getattr(args, "label", GALANGAL_LABEL) or GALANGAL_LABEL

    try:
        issues = list_issues(label=label, limit=args.limit if hasattr(args, "limit") else 50)
    except GitHubError as e:
        print_error(f"Failed to list issues: {e}")
        return 1

    if not issues:
        print_info(f"No open issues found with label '{label}'")
        console.print(f"\n[dim]To tag an issue for galangal, add the '{label}' label.[/dim]")
        return 0

    # Display table
    table = Table(title=f"Issues with '{label}' label")
    table.add_column("#", style="cyan", width=6)
    table.add_column("Title", style="bold", max_width=50)
    table.add_column("Labels", style="dim")
    table.add_column("Author", style="dim")

    for issue in issues:
        other_labels = [lbl for lbl in issue.labels if lbl != label]
        labels_str = ", ".join(other_labels[:3])
        if len(other_labels) > 3:
            labels_str += f" +{len(other_labels) - 3}"

        table.add_row(
            str(issue.number),
            issue.title[:50] + ("..." if len(issue.title) > 50 else ""),
            labels_str,
            issue.author,
        )

    console.print(table)
    console.print(f"\n[dim]Found {len(issues)} issue(s)[/dim]")

    return 0


def cmd_github_run(args: argparse.Namespace) -> int:
    """Process all galangal-labeled GitHub issues headlessly."""
    from galangal.commands.start import create_task
    from galangal.core.state import TaskType, load_state
    from galangal.core.tasks import generate_task_name, task_name_exists
    from galangal.core.workflow import run_workflow
    from galangal.github.client import GitHubClient, GitHubError
    from galangal.github.issues import GALANGAL_LABEL, list_issues, mark_issue_in_progress

    console.print("\n[bold]GitHub Issues Batch Processor[/bold]\n")

    # Check setup
    client = GitHubClient()
    check = client.check_setup()

    if not check.is_ready:
        print_error("GitHub integration not ready. Run 'galangal github check' for details.")
        return 1

    # List issues
    label = getattr(args, "label", GALANGAL_LABEL) or GALANGAL_LABEL
    dry_run = getattr(args, "dry_run", False)

    try:
        issues = list_issues(label=label)
    except GitHubError as e:
        print_error(f"Failed to list issues: {e}")
        return 1

    if not issues:
        print_info(f"No open issues found with label '{label}'")
        return 0

    console.print(f"Found {len(issues)} issue(s) to process\n")
    console.print("[dim]─────────────────────────────────────[/dim]")

    if dry_run:
        print_info("DRY RUN - no tasks will be created\n")
        for issue in issues:
            console.print(f"  [cyan]#{issue.number}[/cyan] {issue.title[:60]}")
        return 0

    # Process each issue
    processed = 0
    failed = 0

    for issue in issues:
        console.print(f"\n[bold]Processing issue #{issue.number}:[/bold] {issue.title[:50]}")

        # Generate task name
        base_name = generate_task_name(f"{issue.title}\n\n{issue.body}")
        task_name = f"issue-{issue.number}-{base_name}"

        # Ensure unique name
        suffix = 2
        while task_name_exists(task_name):
            task_name = f"issue-{issue.number}-{base_name}-{suffix}"
            suffix += 1

        # Infer task type from labels
        type_hint = issue.get_task_type_hint()
        type_map = {
            "feature": TaskType.FEATURE,
            "bug_fix": TaskType.BUG_FIX,
            "refactor": TaskType.REFACTOR,
            "chore": TaskType.CHORE,
            "docs": TaskType.DOCS,
            "hotfix": TaskType.HOTFIX,
        }
        task_type = type_map.get(type_hint, TaskType.FEATURE)

        # Download screenshots from issue body
        screenshots = None
        try:
            from galangal.core.state import get_task_dir
            from galangal.github.images import download_issue_images

            if issue.body:
                task_dir = get_task_dir(task_name)
                task_dir.mkdir(parents=True, exist_ok=True)
                screenshots = download_issue_images(issue.body, task_dir)
                if screenshots:
                    print_info(f"Downloaded {len(screenshots)} screenshot(s)")
        except Exception as e:
            print_warning(f"Screenshot download failed: {e}")

        # Create task
        description = f"{issue.title}\n\n{issue.body}"
        success, msg = create_task(
            task_name,
            description,
            task_type,
            github_issue=issue.number,
            github_repo=check.repo_name,
            screenshots=screenshots,
        )

        if not success:
            print_error(f"Failed to create task: {msg}")
            failed += 1
            break  # Stop on first failure

        print_success(f"Created task: {task_name}")

        # Mark issue as in-progress
        try:
            mark_issue_in_progress(issue.number)
            print_info("Marked issue as in-progress")
        except Exception:
            pass

        # Run workflow
        state = load_state(task_name)
        if state:
            console.print("[dim]Running workflow...[/dim]")
            result = run_workflow(state)

            if result in ("done", "complete"):
                print_success(f"Issue #{issue.number} completed successfully")
                processed += 1
            else:
                print_warning(f"Issue #{issue.number} workflow ended with: {result}")
                failed += 1
                break  # Stop on first failure

    # Summary
    console.print("\n[dim]─────────────────────────────────────[/dim]")
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Processed: {processed}")
    console.print(f"  Failed: {failed}")
    console.print(f"  Remaining: {len(issues) - processed - failed}")

    return 0 if failed == 0 else 1
