"""
Entry points for TUI-based stage execution.
"""


def run_stage_with_tui(
    task_name: str,
    stage: str,
    branch: str,
    attempt: int,
    prompt: str,
) -> tuple[bool, str]:
    """Run a single stage with TUI."""
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
