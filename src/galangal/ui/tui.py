"""
Textual TUI for stage execution display.
"""

import time
from datetime import datetime
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Static, RichLog
from textual.binding import Binding

from galangal.ai.claude import ClaudeBackend


class StageUI:
    """Interface for stage execution UI updates."""

    def set_status(self, status: str, detail: str = "") -> None:
        """Update the current status."""
        pass

    def add_activity(self, activity: str, icon: str = "•") -> None:
        """Add an activity to the log."""
        pass

    def add_raw_line(self, line: str) -> None:
        """Add a raw output line (for verbose mode)."""
        pass

    def set_turns(self, turns: int) -> None:
        """Update the turn count."""
        pass

    def finish(self, success: bool) -> None:
        """Mark the stage as finished."""
        pass


class StageTUIApp(App):
    """Textual app for stage execution."""

    CSS = """
    #status-panel {
        height: 3;
        background: $surface;
        padding: 0 1;
    }

    #activity-log {
        height: 100%;
        border: solid $primary;
    }

    .status-label {
        color: $text;
    }

    .status-value {
        color: $success;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("v", "toggle_verbose", "Verbose", show=True),
    ]

    def __init__(
        self,
        task_name: str,
        stage: str,
        branch: str,
        attempt: int,
        prompt: str,
    ):
        super().__init__()
        self.task_name = task_name
        self.stage = stage
        self.branch = branch
        self.attempt = attempt
        self.prompt = prompt
        self.verbose = False
        self.result: tuple[bool, str] = (False, "")
        self._status = "starting"
        self._detail = ""
        self._turns = 0
        self._start_time = time.time()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(id="status-line"),
            id="status-panel",
        )
        yield Vertical(
            RichLog(id="activity-log", highlight=True, markup=True),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Start the stage execution."""
        self._update_status_line()
        self.run_worker(self._execute_stage, exclusive=True)

    def _update_status_line(self) -> None:
        """Update the status line."""
        elapsed = int(time.time() - self._start_time)
        elapsed_str = f"{elapsed // 60}:{elapsed % 60:02d}"

        status_line = self.query_one("#status-line", Static)
        status_line.update(
            f"[bold]{self.task_name}[/bold] | "
            f"Stage: [cyan]{self.stage}[/cyan] | "
            f"Status: [green]{self._status}[/green] {self._detail} | "
            f"Turns: {self._turns} | "
            f"Time: {elapsed_str}"
        )

    async def _execute_stage(self) -> None:
        """Execute the stage using Claude."""
        backend = ClaudeBackend()

        # Create a UI adapter
        ui = TUIAdapter(self)

        self.result = backend.invoke(
            prompt=self.prompt,
            timeout=14400,
            max_turns=200,
            ui=ui,
        )

        # Finish
        success, _ = self.result
        if success:
            self._status = "complete"
            self._add_activity("[green]Stage completed successfully[/green]", "✓")
        else:
            self._status = "failed"
            self._add_activity("[red]Stage failed[/red]", "✗")

        self._update_status_line()
        # Auto-exit after a short delay
        self.set_timer(1.5, self.exit)

    def _add_activity(self, activity: str, icon: str = "•") -> None:
        """Add an activity to the log."""
        log = self.query_one("#activity-log", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log.write(f"[dim]{timestamp}[/dim] {icon} {activity}")

    def action_toggle_verbose(self) -> None:
        """Toggle verbose mode."""
        self.verbose = not self.verbose


class TUIAdapter(StageUI):
    """Adapter to connect ClaudeBackend to TUI."""

    def __init__(self, app: StageTUIApp):
        self.app = app

    def set_status(self, status: str, detail: str = "") -> None:
        self.app._status = status
        self.app._detail = detail
        self.app.call_from_thread(self.app._update_status_line)

    def add_activity(self, activity: str, icon: str = "•") -> None:
        self.app.call_from_thread(self.app._add_activity, activity, icon)

    def add_raw_line(self, line: str) -> None:
        if self.app.verbose:
            log = self.app.query_one("#activity-log", RichLog)
            self.app.call_from_thread(log.write, f"[dim]{line.strip()}[/dim]")

    def set_turns(self, turns: int) -> None:
        self.app._turns = turns
        self.app.call_from_thread(self.app._update_status_line)

    def finish(self, success: bool) -> None:
        pass


def run_stage_with_tui(
    task_name: str,
    stage: str,
    branch: str,
    attempt: int,
    prompt: str,
) -> tuple[bool, str]:
    """Run a stage with TUI display."""
    app = StageTUIApp(
        task_name=task_name,
        stage=stage,
        branch=branch,
        attempt=attempt,
        prompt=prompt,
    )
    app.run()
    return app.result
