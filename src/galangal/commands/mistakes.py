"""
CLI commands for managing tracked mistakes.

Provides commands to list, search, and manage the mistake database
that helps prevent recurring AI errors.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from rich.console import Console
from rich.table import Table

console = Console()


def _check_dependencies() -> bool:
    """Check if mistake tracking dependencies are available."""
    try:
        from galangal.mistakes import MistakeTracker

        # Try to initialize (will fail if sentence-transformers not installed)
        MistakeTracker()
        return True
    except ImportError as e:
        console.print(
            "[yellow]Mistake tracking requires the full installation.[/yellow]\n\n"
            "Install with: [bold]pip install galangal-orchestrate[full][/bold]\n\n"
            "[dim]This adds ~2GB (includes PyTorch for local embeddings).[/dim]\n"
            f"\nError: {e}"
        )
        return False


def cmd_mistakes_list(args: argparse.Namespace) -> int:
    """List tracked mistakes."""
    if not _check_dependencies():
        return 1

    from galangal.mistakes import MistakeTracker

    tracker = MistakeTracker()
    mistakes = tracker.get_all_mistakes(limit=args.limit)

    if not mistakes:
        console.print("[dim]No mistakes tracked yet.[/dim]")
        console.print(
            "\nMistakes are automatically logged when:\n"
            "  - A stage fails and rolls back\n"
            "  - You interrupt (Ctrl+I) with feedback\n"
        )
        return 0

    # Filter by stage if specified
    if args.stage:
        stage_upper = args.stage.upper()
        mistakes = [m for m in mistakes if m.stage == stage_upper]
        if not mistakes:
            console.print(f"[dim]No mistakes found for stage: {args.stage}[/dim]")
            return 0

    table = Table(title="Tracked Mistakes", show_lines=True)
    table.add_column("ID", style="dim", width=4)
    table.add_column("Stage", style="cyan", width=8)
    table.add_column("Count", justify="right", width=5)
    table.add_column("Description", width=40)
    table.add_column("Last Task", style="dim", width=20)
    table.add_column("Age", style="dim", width=8)

    for m in mistakes:
        age_days = m.age_days
        if age_days < 1:
            age_str = "today"
        elif age_days < 7:
            age_str = f"{int(age_days)}d ago"
        elif age_days < 30:
            age_str = f"{int(age_days / 7)}w ago"
        else:
            age_str = f"{int(age_days / 30)}mo ago"

        # Truncate description
        desc = m.description
        if len(desc) > 40:
            desc = desc[:37] + "..."

        table.add_row(
            str(m.id),
            m.stage,
            str(m.occurrence_count),
            desc,
            m.last_task[:20] if len(m.last_task) > 20 else m.last_task,
            age_str,
        )

    console.print(table)
    console.print(f"\n[dim]Showing {len(mistakes)} mistake(s). Use --limit to see more.[/dim]")

    return 0


def cmd_mistakes_stats(args: argparse.Namespace) -> int:
    """Show mistake statistics."""
    if not _check_dependencies():
        return 1

    from galangal.mistakes import MistakeTracker

    tracker = MistakeTracker()
    stats = tracker.get_stats()

    console.print("\n[bold]Mistake Tracking Statistics[/bold]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Unique mistakes", str(stats["total_unique"]))
    table.add_row("Total occurrences", str(stats["total_occurrences"]))
    table.add_row("Vector search", "Enabled" if stats["vss_enabled"] else "Disabled (fallback mode)")

    console.print(table)

    if stats["by_stage"]:
        console.print("\n[bold]By Stage:[/bold]")
        stage_table = Table(show_header=False, box=None, padding=(0, 2))
        stage_table.add_column("Stage", style="cyan")
        stage_table.add_column("Count", justify="right")

        for stage, count in sorted(stats["by_stage"].items(), key=lambda x: -x[1]):
            stage_table.add_row(stage, str(count))

        console.print(stage_table)

    if stats["total_unique"] == 0:
        console.print(
            "\n[dim]No mistakes tracked yet. They will be logged automatically "
            "during rollbacks and interrupts.[/dim]"
        )

    return 0


def cmd_mistakes_search(args: argparse.Namespace) -> int:
    """Search for similar mistakes."""
    if not _check_dependencies():
        return 1

    from galangal.mistakes import MistakeTracker

    tracker = MistakeTracker()

    console.print(f"\n[dim]Searching for mistakes similar to:[/dim] {args.query}\n")

    # Use the embedding search
    embedding = tracker._embed(args.query)
    similar = tracker._find_similar(embedding, threshold=0.7, limit=10)

    if not similar:
        console.print("[yellow]No similar mistakes found.[/yellow]")
        return 0

    table = Table(title="Similar Mistakes", show_lines=True)
    table.add_column("ID", style="dim", width=4)
    table.add_column("Stage", style="cyan", width=8)
    table.add_column("Count", justify="right", width=5)
    table.add_column("Description", width=50)
    table.add_column("Prevention", width=50)

    for m in similar:
        table.add_row(
            str(m.id),
            m.stage,
            str(m.occurrence_count),
            m.description,
            m.feedback[:50] + "..." if len(m.feedback) > 50 else m.feedback,
        )

    console.print(table)

    return 0


def cmd_mistakes_delete(args: argparse.Namespace) -> int:
    """Delete a mistake by ID."""
    if not _check_dependencies():
        return 1

    from galangal.mistakes import MistakeTracker
    from rich.prompt import Confirm

    tracker = MistakeTracker()

    # Find the mistake first
    row = tracker.conn.execute(
        "SELECT * FROM mistakes WHERE id = ?", [args.id]
    ).fetchone()

    if not row:
        console.print(f"[red]Mistake with ID {args.id} not found.[/red]")
        return 1

    console.print(f"\n[bold]Mistake #{args.id}:[/bold]")
    console.print(f"  Stage: {row['stage']}")
    console.print(f"  Description: {row['description']}")
    console.print(f"  Occurrences: {row['occurrence_count']}")

    if not Confirm.ask("\nDelete this mistake?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        return 0

    tracker.delete(args.id)
    console.print(f"[green]Deleted mistake #{args.id}[/green]")

    return 0
