"""
Stats command - show project metrics and insights.
"""

import argparse

from rich.console import Console
from rich.table import Table

from galangal.core.metrics import ProjectMetrics, StageMetrics, load_metrics
from galangal.core.state import Stage

console = Console()


def cmd_stats(args: argparse.Namespace) -> int:
    """Show project metrics and insights."""
    metrics = load_metrics()

    if not metrics.stages:
        console.print("[yellow]No metrics collected yet.[/yellow]")
        console.print("Metrics are recorded as you complete workflow stages.")
        return 0

    # Filter to specific stage if requested
    if args.stage:
        stage_name = args.stage.upper()
        if stage_name not in metrics.stages:
            console.print(f"[yellow]No metrics for stage: {stage_name}[/yellow]")
            return 0
        _show_stage_stats(stage_name, metrics.stages[stage_name], detailed=args.detailed)
        return 0

    # Show overview
    console.print("\n[bold]Project Stage Metrics[/bold]\n")

    # Summary table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Stage", style="cyan")
    table.add_column("Runs", justify="right")
    table.add_column("Success Rate", justify="right")
    table.add_column("Avg Attempts", justify="right")
    table.add_column("Avg Turns", justify="right")
    table.add_column("Status", justify="center")

    # Sort stages by canonical order
    stage_order = [s.value for s in Stage]
    sorted_stages = sorted(
        metrics.stages.items(),
        key=lambda x: stage_order.index(x[0]) if x[0] in stage_order else 999
    )

    for stage_name, stage_metrics in sorted_stages:
        if stage_metrics.total_runs == 0:
            continue

        success_rate = stage_metrics.success_rate
        avg_attempts = stage_metrics.avg_attempts
        avg_turns = stage_metrics.avg_turns

        # Color-code success rate
        if success_rate >= 0.9:
            rate_str = f"[green]{success_rate:.0%}[/green]"
            status = "[green]Good[/green]"
        elif success_rate >= 0.7:
            rate_str = f"[yellow]{success_rate:.0%}[/yellow]"
            status = "[yellow]OK[/yellow]"
        else:
            rate_str = f"[red]{success_rate:.0%}[/red]"
            status = "[red]Needs attention[/red]"

        turns_str = f"{avg_turns:.1f}" if avg_turns else "-"

        table.add_row(
            stage_name,
            str(stage_metrics.total_runs),
            rate_str,
            f"{avg_attempts:.1f}",
            turns_str,
            status,
        )

    console.print(table)

    # Show insights
    _show_insights(metrics)

    if args.detailed:
        console.print("\n[bold]Detailed Breakdown[/bold]\n")
        for stage_name, stage_metrics in sorted_stages:
            if stage_metrics.total_runs > 0:
                _show_stage_stats(stage_name, stage_metrics, detailed=True)

    return 0


def _show_stage_stats(stage_name: str, stage_metrics: StageMetrics, detailed: bool = False) -> None:
    """Show stats for a single stage."""
    console.print(f"\n[bold cyan]{stage_name}[/bold cyan]")
    console.print(f"  Runs: {stage_metrics.total_runs}")
    console.print(f"  Success rate: {stage_metrics.success_rate:.0%}")
    console.print(f"  Avg attempts: {stage_metrics.avg_attempts:.1f}")
    if stage_metrics.avg_turns:
        console.print(f"  Avg turns: {stage_metrics.avg_turns:.1f}")

    # Show common failures if any
    common_failures = stage_metrics.common_failures(3)
    if common_failures:
        console.print("\n  [yellow]Common failures:[/yellow]")
        for reason, count in common_failures:
            console.print(f"    - {reason} ({count}x)")

    if detailed:
        console.print("\n  [dim]Recent runs:[/dim]")
        for run in stage_metrics.runs[-5:]:
            status = "[green]OK[/green]" if run.success else "[red]FAIL[/red]"
            timestamp = run.timestamp[:10] if run.timestamp else "?"
            console.print(f"    {timestamp} {status} (attempts: {run.attempts})")


def _show_insights(metrics: ProjectMetrics) -> None:
    """Show actionable insights based on metrics."""
    insights = []

    for stage_name, stage_metrics in metrics.stages.items():
        if stage_metrics.total_runs < 3:
            continue

        # High failure rate
        if stage_metrics.failure_rate > 0.3:
            common = stage_metrics.common_failures(1)
            if common:
                reason = common[0][0]
                insights.append(
                    f"[yellow]{stage_name}[/yellow] has {stage_metrics.failure_rate:.0%} failure rate. "
                    f"Common issue: {reason}"
                )
            else:
                insights.append(
                    f"[yellow]{stage_name}[/yellow] has {stage_metrics.failure_rate:.0%} failure rate."
                )

        # High retry rate
        if stage_metrics.avg_attempts > 2.5:
            insights.append(
                f"[yellow]{stage_name}[/yellow] averages {stage_metrics.avg_attempts:.1f} attempts. "
                "Consider adding guidance to the stage prompt."
            )

    if insights:
        console.print("\n[bold]Insights[/bold]")
        for insight in insights:
            console.print(f"  - {insight}")
    else:
        console.print("\n[green]All stages performing well.[/green]")
