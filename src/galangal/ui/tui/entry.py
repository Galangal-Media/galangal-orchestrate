"""
Entry points for TUI-based stage execution.
"""

import os


def _run_simple_mode(
    task_name: str,
    stage: str,
    attempt: int,
    prompt: str,
) -> tuple[bool, str]:
    """Run stage without TUI."""
    from rich.console import Console

    from galangal.ai.claude import ClaudeBackend
    from galangal.ui.tui.adapters import SimpleConsoleUI

    console = Console()
    console.print(f"\n[bold]Running {stage}[/bold] (attempt {attempt})")

    backend = ClaudeBackend()
    ui = SimpleConsoleUI(task_name, stage)

    result = backend.invoke(
        prompt=prompt,
        timeout=14400,
        max_turns=200,
        ui=ui,
    )
    ui.finish(result[0])
    return result


def run_stage_with_tui(
    task_name: str,
    stage: str,
    branch: str,
    attempt: int,
    prompt: str,
) -> tuple[bool, str]:
    """Run a single stage with TUI."""
    if os.environ.get("GALANGAL_NO_TUI"):
        return _run_simple_mode(task_name, stage, attempt, prompt)

    try:
        from galangal.ui.tui.app import StageTUIApp

        app = StageTUIApp(
            task_name=task_name,
            stage=stage,
            branch=branch,
            attempt=attempt,
            prompt=prompt,
        )
        app.run()
        return app.result
    except Exception as e:
        from rich.console import Console

        console = Console()
        console.print(f"[yellow]TUI error: {e}. Falling back to simple mode.[/yellow]")
        return _run_simple_mode(task_name, stage, attempt, prompt)
