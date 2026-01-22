"""
Archive command - move old completed tasks to archive.
"""

import argparse
import gzip
import json
import re
import shutil
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

from galangal.config.loader import get_done_dir, get_tasks_dir, require_initialized
from galangal.ui.console import console, print_error, print_info, print_success


def parse_duration(duration_str: str) -> timedelta | None:
    """
    Parse a duration string like '30d', '2w', '6m' into timedelta.

    Supported formats:
    - Nd: N days (e.g., '30d' = 30 days)
    - Nw: N weeks (e.g., '2w' = 14 days)
    - Nm: N months (approximate, 30 days per month)

    Returns None if parsing fails.
    """
    match = re.match(r"^(\d+)([dwm])$", duration_str.lower())
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    elif unit == "m":
        return timedelta(days=value * 30)  # Approximate

    return None


def get_archive_dir() -> Path:
    """Get the archive directory path."""
    return get_tasks_dir() / ".archive"


def get_archive_index_path() -> Path:
    """Get the archive index file path."""
    return get_archive_dir() / "index.json"


def load_archive_index() -> dict[str, dict]:
    """Load the archive index."""
    index_path = get_archive_index_path()
    if index_path.exists():
        try:
            return json.loads(index_path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_archive_index(index: dict[str, dict]) -> None:
    """Save the archive index."""
    index_path = get_archive_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2))


def get_task_completion_time(task_dir: Path) -> datetime | None:
    """
    Get the completion time of a task from its state file.

    Returns None if the state file doesn't exist or can't be parsed.
    """
    state_file = task_dir / "state.json"
    if not state_file.exists():
        return None

    try:
        data = json.loads(state_file.read_text())
        # Try different time fields
        for field in ["completed_at", "end_time", "start_time"]:
            if field in data and data[field]:
                try:
                    return datetime.fromisoformat(data[field].replace("Z", "+00:00"))
                except ValueError:
                    continue
        # Fallback to file modification time
        return datetime.fromtimestamp(state_file.stat().st_mtime)
    except (json.JSONDecodeError, OSError):
        return None


def get_task_metadata(task_dir: Path) -> dict:
    """Extract metadata from a task for the archive index."""
    state_file = task_dir / "state.json"
    metadata = {
        "name": task_dir.name,
        "archived_at": datetime.now().isoformat(),
    }

    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            metadata.update({
                "task_type": data.get("task_type", "unknown"),
                "description": data.get("task_description", "")[:200],
                "stage": data.get("stage", "unknown"),
                "start_time": data.get("start_time"),
                "github_issue": data.get("github_issue"),
            })
        except json.JSONDecodeError:
            pass

    return metadata


def archive_task(
    task_dir: Path,
    archive_dir: Path,
    compress: bool = False,
) -> tuple[bool, str]:
    """
    Archive a single task.

    Args:
        task_dir: Path to the task directory
        archive_dir: Path to the archive directory
        compress: If True, compress the task as .tar.gz

    Returns:
        Tuple of (success, message)
    """
    task_name = task_dir.name
    archive_dir.mkdir(parents=True, exist_ok=True)

    if compress:
        # Create compressed archive
        archive_path = archive_dir / f"{task_name}.tar.gz"
        if archive_path.exists():
            return False, f"Archive already exists: {archive_path.name}"

        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(task_dir, arcname=task_name)
            # Remove original
            shutil.rmtree(task_dir)
            return True, f"Archived (compressed): {task_name}"
        except OSError as e:
            return False, f"Failed to compress {task_name}: {e}"
    else:
        # Move without compression
        dest_path = archive_dir / task_name
        if dest_path.exists():
            return False, f"Archive already exists: {task_name}"

        try:
            shutil.move(str(task_dir), str(dest_path))
            return True, f"Archived: {task_name}"
        except OSError as e:
            return False, f"Failed to archive {task_name}: {e}"


def list_archivable_tasks(before: timedelta | None = None) -> list[tuple[Path, datetime | None]]:
    """
    List tasks that can be archived from the done directory.

    Args:
        before: Only include tasks completed before this duration ago

    Returns:
        List of (task_dir, completion_time) tuples
    """
    done_dir = get_done_dir()
    if not done_dir.exists():
        return []

    cutoff = datetime.now() - before if before else None
    tasks = []

    for task_dir in done_dir.iterdir():
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue

        completion_time = get_task_completion_time(task_dir)

        # Filter by age if cutoff specified
        if cutoff and completion_time and completion_time > cutoff:
            continue

        tasks.append((task_dir, completion_time))

    # Sort by completion time (oldest first)
    return sorted(tasks, key=lambda x: x[1] or datetime.min)


def cmd_archive(args: argparse.Namespace) -> int:
    """Archive completed tasks."""
    if not require_initialized():
        return 1

    # Parse duration
    before = None
    if args.before:
        before = parse_duration(args.before)
        if before is None:
            print_error(f"Invalid duration format: {args.before}")
            print_info("Use formats like: 30d (days), 2w (weeks), 6m (months)")
            return 1

    # Get archivable tasks
    tasks = list_archivable_tasks(before)

    if not tasks:
        if before:
            print_info(f"No completed tasks older than {args.before}")
        else:
            print_info("No completed tasks to archive")
        return 0

    # Show what will be archived
    console.print(f"\n[bold]Tasks to archive:[/] {len(tasks)}\n")
    for task_dir, completion_time in tasks[:10]:  # Show first 10
        time_str = completion_time.strftime("%Y-%m-%d") if completion_time else "unknown"
        console.print(f"  [#a89984]{time_str}[/]  {task_dir.name}")
    if len(tasks) > 10:
        console.print(f"  [#7c6f64]... and {len(tasks) - 10} more[/]")
    console.print()

    # Confirm unless --force
    if not args.force:
        console.print("[#fabd2f]This will move tasks to .archive/[/]")
        if args.compress:
            console.print("[#fabd2f]Tasks will be compressed as .tar.gz files[/]")
        response = console.input("Continue? [y/N] ")
        if response.lower() != "y":
            print_info("Cancelled")
            return 0

    # Archive tasks
    archive_dir = get_archive_dir()
    index = load_archive_index()
    archived = 0
    failed = 0

    for task_dir, completion_time in tasks:
        # Get metadata before archiving
        metadata = get_task_metadata(task_dir)

        success, message = archive_task(task_dir, archive_dir, compress=args.compress)
        if success:
            console.print(f"  [#b8bb26]✓[/] {message}")
            # Update index
            index[task_dir.name] = metadata
            archived += 1
        else:
            console.print(f"  [#fb4934]✗[/] {message}")
            failed += 1

    # Save index
    save_archive_index(index)

    # Summary
    console.print()
    if archived > 0:
        print_success(f"Archived {archived} task(s)")
    if failed > 0:
        print_error(f"Failed to archive {failed} task(s)")

    return 0 if failed == 0 else 1


def cmd_archive_list(args: argparse.Namespace) -> int:
    """List archived tasks."""
    if not require_initialized():
        return 1

    index = load_archive_index()
    archive_dir = get_archive_dir()

    if not index and not archive_dir.exists():
        print_info("No archived tasks")
        return 0

    # Also check for any unindexed archives
    archived_items = set(index.keys())
    if archive_dir.exists():
        for item in archive_dir.iterdir():
            if item.name == "index.json":
                continue
            name = item.stem if item.suffix == ".gz" else item.name
            if name.endswith(".tar"):
                name = name[:-4]
            archived_items.add(name)

    if not archived_items:
        print_info("No archived tasks")
        return 0

    console.print(f"\n[bold]Archived tasks:[/] {len(archived_items)}\n")

    # Search filter
    search = args.search.lower() if args.search else None

    for name in sorted(archived_items):
        metadata = index.get(name, {})
        desc = metadata.get("description", "")[:50]
        task_type = metadata.get("task_type", "?")
        archived_at = metadata.get("archived_at", "")[:10]

        # Apply search filter
        if search and search not in name.lower() and search not in desc.lower():
            continue

        console.print(
            f"  [#a89984]{archived_at or '?':10}[/]  "
            f"[#83a598]{task_type:10}[/]  "
            f"[#ebdbb2]{name}[/]"
        )
        if desc:
            console.print(f"              [#7c6f64]{desc}[/]")

    console.print()
    return 0


def cmd_archive_restore(args: argparse.Namespace) -> int:
    """Restore an archived task."""
    if not require_initialized():
        return 1

    task_name = args.task_name
    archive_dir = get_archive_dir()
    done_dir = get_done_dir()

    # Check for compressed archive
    compressed_path = archive_dir / f"{task_name}.tar.gz"
    uncompressed_path = archive_dir / task_name

    if compressed_path.exists():
        # Extract compressed archive
        try:
            with tarfile.open(compressed_path, "r:gz") as tar:
                tar.extractall(done_dir)
            compressed_path.unlink()
            print_success(f"Restored: {task_name}")
        except (tarfile.TarError, OSError) as e:
            print_error(f"Failed to restore: {e}")
            return 1
    elif uncompressed_path.exists():
        # Move uncompressed directory
        try:
            shutil.move(str(uncompressed_path), str(done_dir / task_name))
            print_success(f"Restored: {task_name}")
        except OSError as e:
            print_error(f"Failed to restore: {e}")
            return 1
    else:
        print_error(f"Archive not found: {task_name}")
        return 1

    # Update index
    index = load_archive_index()
    if task_name in index:
        del index[task_name]
        save_archive_index(index)

    return 0
