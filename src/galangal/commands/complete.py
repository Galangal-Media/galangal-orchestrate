"""
galangal complete - Complete a task, commit, and create PR.
"""

import argparse
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from rich.prompt import Prompt

from galangal.ai import get_backend_with_fallback
from galangal.config.loader import get_config, get_done_dir, get_project_root
from galangal.core.artifacts import read_artifact, run_command
from galangal.core.state import Stage, get_task_dir
from galangal.core.tasks import clear_active_task
from galangal.ui.console import console, print_error, print_success, print_warning


def generate_pr_title(task_name: str, description: str, task_type: str) -> str:
    """Generate a concise PR title using AI."""
    config = get_config()
    backend = get_backend_with_fallback(config.ai.default, config=config)

    prompt = f"""Generate a concise pull request title for this task.

Task: {task_name}
Type: {task_type}
Description: {description[:500]}

Requirements:
1. Max 72 characters
2. Start with type prefix based on task type:
   - Feature → "feat: ..."
   - Bug Fix → "fix: ..."
   - Refactor → "refactor: ..."
   - Chore → "chore: ..."
   - Docs → "docs: ..."
   - Hotfix → "fix: ..."
3. Be specific about what changed
4. Use imperative mood ("Add feature" not "Added feature")
5. No period at end

Output ONLY the title, nothing else."""

    title = backend.generate_text(prompt, timeout=30)
    if title:
        title = title.split("\n")[0].strip()
        return title[:72] if len(title) > 72 else title

    # Fallback
    return description[:72] if len(description) > 72 else description


def generate_commit_summary(
    task_name: str,
    description: str,
    spec: str | None = None,
    plan: str | None = None,
) -> str:
    """Generate a commit message summary using AI.

    Args:
        task_name: Name of the task
        description: Task description
        spec: Pre-read SPEC.md content (optional, reads from disk if not provided)
        plan: Pre-read PLAN.md content (optional, reads from disk if not provided)
    """
    config = get_config()
    backend = get_backend_with_fallback(config.ai.default, config=config)
    base_branch = config.pr.base_branch

    # Use provided artifacts or read from disk
    if spec is None:
        spec = read_artifact("SPEC.md", task_name) or ""
    if plan is None:
        plan = read_artifact("PLAN.md", task_name) or ""

    code, diff_stat, _ = run_command(["git", "diff", "--stat", f"{base_branch}...HEAD"])
    code, changed_files, _ = run_command(["git", "diff", "--name-only", f"{base_branch}...HEAD"])

    prompt = f"""Generate a concise git commit message for this task. Follow conventional commit format.

Task: {task_name}
Description: {description}

Specification summary:
{spec[:1000] if spec else "(none)"}

Implementation plan summary:
{plan[:800] if plan else "(none)"}

Files changed:
{changed_files[:1000] if changed_files else "(none)"}

Requirements:
1. First line: type(scope): brief description (max 72 chars)
   - Types: feat, fix, refactor, chore, docs, test, style, perf
2. Blank line
3. Body: 2-4 bullet points summarizing key changes
4. Do NOT include any co-authored-by or generated-by lines

Output ONLY the commit message, nothing else."""

    summary = backend.generate_text(prompt, timeout=60)
    if summary:
        return summary.strip()

    return f"{description[:72]}"


def create_pull_request(
    task_name: str,
    description: str,
    task_type: str,
    github_issue: int | None = None,
) -> tuple[bool, str]:
    """Create a pull request for the task branch.

    Args:
        task_name: Name of the task
        description: Task description
        task_type: Type of task (Feature, Bug Fix, etc.)
        github_issue: Optional GitHub issue number to link

    Returns:
        Tuple of (success, pr_url_or_error)
    """
    config = get_config()
    branch_name = config.branch_pattern.format(task_name=task_name)
    base_branch = config.pr.base_branch

    code, current_branch, _ = run_command(["git", "branch", "--show-current"])
    current_branch = current_branch.strip()

    if current_branch != branch_name:
        code, _, err = run_command(["git", "checkout", branch_name])
        if code != 0:
            return False, f"Could not switch to branch {branch_name}: {err}"

    code, out, err = run_command(["git", "push", "-u", "origin", branch_name])
    if code != 0:
        if "Everything up-to-date" not in out and "Everything up-to-date" not in err:
            return False, f"Failed to push branch: {err or out}"

    spec_content = read_artifact("SPEC.md", task_name) or description
    summary_content = read_artifact("SUMMARY.md", task_name)

    console.print("[dim]Generating PR title...[/dim]")
    pr_title = generate_pr_title(task_name, description, task_type)

    # Prefix PR title with issue reference if linked
    if github_issue:
        pr_title = f"Issue #{github_issue}: {pr_title}"

    # Build PR body - prefer summary if available, fall back to spec
    if summary_content:
        # Use summary (truncate if needed)
        summary_truncated = summary_content[:2000] if len(summary_content) > 2000 else summary_content
        pr_body = f"""{summary_truncated}

"""
    else:
        # Fall back to spec content
        pr_body = f"""## Summary
{spec_content[:1500] if len(spec_content) > 1500 else spec_content}

"""
    # Add issue closing reference if linked
    if github_issue:
        pr_body += f"Closes #{github_issue}\n\n"

    pr_body += "---\n"

    # Add codex review if configured
    if config.pr.codex_review:
        pr_body += "@codex review\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(pr_body)
        body_file = f.name

    try:
        code, out, err = run_command(
            [
                "gh",
                "pr",
                "create",
                "--title",
                pr_title,
                "--body-file",
                body_file,
                "--base",
                base_branch,
            ]
        )
    finally:
        Path(body_file).unlink(missing_ok=True)

    if code != 0:
        combined_output = (out + err).lower()
        if "already exists" in combined_output:
            return True, "PR already exists"
        if "pull request create failed" in combined_output:
            code2, pr_url, _ = run_command(["gh", "pr", "view", "--json", "url", "-q", ".url"])
            if code2 == 0 and pr_url.strip():
                return True, pr_url.strip()
        return False, f"Failed to create PR: {err or out}"

    pr_url = out.strip()

    # Comment on issue with PR link if linked
    if github_issue and pr_url:
        try:
            from galangal.github.issues import mark_issue_pr_created

            mark_issue_pr_created(github_issue, pr_url)
        except Exception:
            pass  # Non-critical

    return True, pr_url


def _squash_stage_commits(
    task_name: str,
    description: str,
    state,
    spec: str | None = None,
    plan: str | None = None,
) -> tuple[bool, str]:
    """Squash all stage commits into one clean commit.

    Called when commit_per_stage is enabled and there are stage commits to squash.

    Args:
        task_name: Name of the task
        description: Task description
        state: WorkflowState with base_commit_sha and stage_commits
        spec: Pre-read SPEC.md content (optional)
        plan: Pre-read PLAN.md content (optional)

    Returns:
        Tuple of (success, message)
    """
    from galangal.core.git_utils import squash_to_base

    if not state.base_commit_sha:
        return False, "No base commit SHA found - cannot squash"

    if not state.stage_commits:
        return False, "No stage commits to squash"

    # Generate commit message
    console.print("[dim]Generating commit summary...[/dim]")
    summary = generate_commit_summary(task_name, description, spec=spec, plan=plan)

    # Build final commit message
    stages = [c["stage"] for c in state.stage_commits]
    commit_msg = f"""{summary}

Task: {task_name}
Stages: {', '.join(stages)}"""

    # Show progress
    console.print(f"[dim]Squashing {len(stages)} commits ({', '.join(stages)})...[/dim]")

    # Perform the squash
    success = squash_to_base(state.base_commit_sha, commit_msg, cwd=None)
    if success:
        return True, f"Squashed {len(stages)} stage commits"
    return False, "Squash failed - try manual commit"


def commit_changes(
    task_name: str,
    description: str,
    spec: str | None = None,
    plan: str | None = None,
    state=None,
) -> tuple[bool, str]:
    """Commit all changes for a task.

    Args:
        task_name: Name of the task
        description: Task description
        spec: Pre-read SPEC.md content (optional)
        plan: Pre-read PLAN.md content (optional)
        state: Optional WorkflowState for commit_per_stage squashing
    """
    config = get_config()

    # If commit_per_stage is enabled and we have stage commits, squash instead
    if (
        config.stages.commit_per_stage
        and state
        and state.stage_commits
        and state.base_commit_sha
    ):
        return _squash_stage_commits(task_name, description, state, spec=spec, plan=plan)

    # Standard commit logic (no stage commits or commit_per_stage disabled)
    code, status_out, _ = run_command(["git", "status", "--porcelain"])
    if code != 0:
        return False, "Failed to check git status"

    if not status_out.strip():
        return True, "No changes to commit"

    changes = [line for line in status_out.strip().split("\n") if line.strip()]
    change_count = len(changes)

    console.print(f"[dim]Committing {change_count} changed files...[/dim]")

    code, _, err = run_command(["git", "add", "-A"])
    if code != 0:
        return False, f"Failed to stage changes: {err}"

    console.print("[dim]Generating commit summary...[/dim]")
    summary = generate_commit_summary(task_name, description, spec=spec, plan=plan)

    commit_msg = f"""{summary}

Task: {task_name}
Changes: {change_count} files"""

    code, out, err = run_command(["git", "commit", "-m", commit_msg])
    if code != 0:
        return False, f"Failed to commit: {err or out}"

    return True, f"Committed {change_count} files"


def finalize_task(
    task_name: str, state, force: bool = False, progress_callback=None
) -> tuple[bool, str]:
    """Finalize a completed task: move to done/, commit, create PR.

    Args:
        task_name: Name of the task to finalize
        state: WorkflowState object
        force: If True, continue even on errors
        progress_callback: Optional callback(message, status) for progress updates.
                          status is one of: 'info', 'success', 'warning', 'error'

    Returns:
        Tuple of (success, pr_url_or_error_message)
    """

    def report(message: str, status: str = "info"):
        if progress_callback:
            progress_callback(message, status)
        else:
            if status == "success":
                print_success(message)
            elif status == "warning":
                print_warning(message)
            elif status == "error":
                print_error(message)
            else:
                console.print(f"[dim]{message}[/dim]")

    config = get_config()
    project_root = get_project_root()
    done_dir = get_done_dir()

    # Pre-read artifacts before moving task (for commit message generation)
    spec = read_artifact("SPEC.md", task_name) or ""
    plan = read_artifact("PLAN.md", task_name) or ""

    # 1. Move to done/
    task_dir = get_task_dir(task_name)
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / task_name

    if dest.exists():
        dest = done_dir / f"{task_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Remove logs directory before moving (not needed after completion)
    logs_dir = task_dir / "logs"
    if logs_dir.exists():
        shutil.rmtree(logs_dir)

    report(f"Moving task to {dest.relative_to(project_root)}/...")
    shutil.move(str(task_dir), str(dest))
    clear_active_task()

    # 2. Commit changes (pass pre-read artifacts since task dir was moved)
    report("Committing changes...")
    success, msg = commit_changes(task_name, state.task_description, spec=spec, plan=plan, state=state)
    if success:
        report(msg, "success")
    else:
        report(msg, "warning")
        if not force and not progress_callback:
            # Only prompt in non-TUI mode
            confirm = Prompt.ask("Continue anyway? [y/N]", default="n").strip().lower()
            if confirm != "y":
                shutil.move(str(dest), str(task_dir))
                from galangal.core.tasks import set_active_task

                set_active_task(task_name)
                report("Aborted. Task restored to original location.", "warning")
                return False, "Aborted by user"

    # 3. Create PR
    report("Creating pull request...")
    success, msg = create_pull_request(
        task_name,
        state.task_description,
        state.task_type.display_name(),
        github_issue=state.github_issue,
    )
    pr_url = ""
    if success:
        pr_url = msg
        report(f"PR: {msg}", "success")
    else:
        report(f"Could not create PR: {msg}", "warning")
        report("You may need to create the PR manually.", "info")

    report(f"Task '{task_name}' completed and moved to {config.tasks_dir}/done/", "success")

    # 4. Switch back to base branch
    run_command(["git", "checkout", config.pr.base_branch])
    report(f"Switched back to {config.pr.base_branch} branch", "info")

    return True, pr_url


def cmd_complete(args: argparse.Namespace) -> int:
    """Move completed task to done/, commit, create PR."""
    from galangal.core.tasks import ensure_active_task_with_state

    active, state = ensure_active_task_with_state()
    if not active or not state:
        return 1

    if state.stage != Stage.COMPLETE:
        print_error(f"Task is at stage {state.stage.value}, not COMPLETE.")
        console.print("Run 'resume' to continue the workflow.")
        return 1

    success, _ = finalize_task(active, state, force=args.force)
    return 0 if success else 1
