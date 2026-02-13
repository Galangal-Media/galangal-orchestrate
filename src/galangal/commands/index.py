"""Task index database management commands."""

import argparse

from galangal.config.loader import require_initialized
from galangal.core.task_index import TaskIndex
from galangal.ui.console import console, print_error, print_success


def cmd_index_stats(args: argparse.Namespace) -> int:
    """Show task index database statistics."""
    if not require_initialized():
        return 1

    try:
        stats = TaskIndex().get_stats()
    except Exception as e:
        print_error(f"Could not read task index: {e}")
        return 1

    console.print("\n[bold]Task Index[/bold]")
    console.print(f"DB: [dim]{stats.db_path}[/dim]")
    console.print(f"Total tasks: {stats.total_tasks}")
    console.print(f"Indexed artifacts: {stats.total_artifacts}")

    if stats.tasks_by_status:
        console.print("\n[bold]By status[/bold]")
        for status in sorted(stats.tasks_by_status):
            console.print(f"  {status:8} {stats.tasks_by_status[status]}")

    console.print()
    return 0


def cmd_index_rebuild(args: argparse.Namespace) -> int:
    """Rebuild the task index from filesystem state."""
    if not require_initialized():
        return 1

    try:
        index = TaskIndex()
        counts = index.rebuild()
        stats = index.get_stats()
    except Exception as e:
        print_error(f"Failed to rebuild task index: {e}")
        return 1

    print_success("Task index rebuild complete.")
    console.print(
        f"Indexed active={counts.get('active', 0)}, "
        f"done={counts.get('done', 0)}, archived={counts.get('archived', 0)}, "
        f"migrated={counts.get('migrated', 0)}, deleted={counts.get('deleted', 0)}"
    )
    console.print(
        f"Current totals: tasks={stats.total_tasks}, artifacts={stats.total_artifacts}"
    )
    return 0


def cmd_index_migrate_artifacts(args: argparse.Namespace) -> int:
    """Migrate legacy filesystem artifacts into DB and delete file copies."""
    if not require_initialized():
        return 1

    try:
        result = TaskIndex().migrate_artifacts(delete_files=True)
    except Exception as e:
        print_error(f"Failed to migrate artifacts: {e}")
        return 1

    print_success("Artifact migration complete.")
    console.print(
        f"Migrated={result.get('migrated', 0)}, deleted={result.get('deleted', 0)}"
    )
    return 0


def cmd_index_compact_done(args: argparse.Namespace) -> int:
    """Keep only PLAN.md and SUMMARY.md in done task folders."""
    if not require_initialized():
        return 1

    try:
        result = TaskIndex().compact_done_markdown()
    except Exception as e:
        print_error(f"Failed to compact done task folders: {e}")
        return 1

    print_success("Done task folders compacted.")
    console.print(
        f"Tasks={result.get('tasks', 0)}, kept={result.get('kept', 0)}, "
        f"restored={result.get('restored', 0)}, deleted={result.get('deleted', 0)}, "
        f"migrated={result.get('migrated', 0)}"
    )
    return 0
