"""
galangal complete - Complete a task, commit, and create PR.
"""

import argparse
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from rich.prompt import Prompt

from galangal.ai.claude import ClaudeBackend
from galangal.config.loader import get_config, get_done_dir, get_project_root
from galangal.core.artifacts import read_artifact, run_command
from galangal.core.state import Stage, get_task_dir, load_state
from galangal.core.tasks import clear_active_task, get_active_task
from galangal.ui.console import console, print_error, print_success, print_warning


def generate_pr_title(task_name: str, description: str, task_type: str) -> str:
    """Generate a concise PR title using AI."""
    backend = ClaudeBackend()

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


def generate_commit_summary(task_name: str, description: str) -> str:
    """Generate a commit message summary using AI."""
    backend = ClaudeBackend()

    spec = read_artifact("SPEC.md", task_name) or ""
    plan = read_artifact("PLAN.md", task_name) or ""

    code, diff_stat, _ = run_command(["git", "diff", "--stat", "main...HEAD"])
    code, changed_files, _ = run_command(["git", "diff", "--name-only", "main...HEAD"])

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


def create_pull_request(task_name: str, description: str, task_type: str) -> tuple[bool, str]:
    """Create a pull request for the task branch."""
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

    console.print("[dim]Generating PR title...[/dim]")
    pr_title = generate_pr_title(task_name, description, task_type)

    # Build PR body
    pr_body = f"""## Summary
{spec_content[:1500] if len(spec_content) > 1500 else spec_content}

---
"""
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
            code2, pr_url, _ = run_command(
                ["gh", "pr", "view", "--json", "url", "-q", ".url"]
            )
            if code2 == 0 and pr_url.strip():
                return True, pr_url.strip()
        return False, f"Failed to create PR: {err or out}"

    return True, out.strip()


def commit_changes(task_name: str, description: str) -> tuple[bool, str]:
    """Commit all changes for a task."""
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
    summary = generate_commit_summary(task_name, description)

    commit_msg = f"""{summary}

Task: {task_name}
Changes: {change_count} files"""

    code, out, err = run_command(["git", "commit", "-m", commit_msg])
    if code != 0:
        return False, f"Failed to commit: {err or out}"

    return True, f"Committed {change_count} files"


def finalize_task(task_name: str, state, force: bool = False, progress_callback=None) -> tuple[bool, str]:
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

    # 1. Move to done/
    task_dir = get_task_dir(task_name)
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / task_name

    if dest.exists():
        dest = done_dir / f"{task_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    report(f"Moving task to {dest.relative_to(project_root)}/...")
    shutil.move(str(task_dir), str(dest))
    clear_active_task()

    # 2. Commit changes
    report("Committing changes...")
    success, msg = commit_changes(task_name, state.task_description)
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
    success, msg = create_pull_request(task_name, state.task_description, state.task_type.display_name())
    pr_url = ""
    if success:
        pr_url = msg
        report(f"PR: {msg}", "success")
    else:
        report(f"Could not create PR: {msg}", "warning")
        report("You may need to create the PR manually.", "info")

    report(f"Task '{task_name}' completed and moved to {config.tasks_dir}/done/", "success")

    # 4. Switch back to main
    run_command(["git", "checkout", config.pr.base_branch])
    report(f"Switched back to {config.pr.base_branch} branch", "info")

    return True, pr_url


def cmd_complete(args: argparse.Namespace) -> int:
    """Move completed task to done/, commit, create PR."""
    active = get_active_task()
    if not active:
        print_error("No active task.")
        return 1

    state = load_state(active)
    if state is None:
        print_error(f"Could not load state for '{active}'.")
        return 1

    if state.stage != Stage.COMPLETE:
        print_error(f"Task is at stage {state.stage.value}, not COMPLETE.")
        console.print("Run 'resume' to continue the workflow.")
        return 1

    success, _ = finalize_task(active, state, force=args.force)
    return 0 if success else 1
