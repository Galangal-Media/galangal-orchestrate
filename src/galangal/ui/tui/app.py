"""
Main Textual TUI application for workflow execution.

Layout:
┌──────────────────────────────────────────────────────────────────┐
│ Task: my-task  Stage: DEV (1/5)  Elapsed: 2:34  Turns: 5         │ Header
├──────────────────────────────────────────────────────────────────┤
│        ● PM ━ ● DESIGN ━ ● DEV ━ ○ TEST ━ ○ QA ━ ○ DONE          │ Progress
├────────────────────────────────────────────────────┬─────────────┤
│                                                    │ Files       │
│ Activity Log                                       │ ─────────── │
│ 11:30:00 • Starting stage...                       │ 📖 file.py  │
│ 11:30:01 📖 Read: file.py                          │ ✏️ test.py  │
│                                                    │             │
├────────────────────────────────────────────────────┴─────────────┤
│ ⠋ Running: waiting for API response                              │ Action
├──────────────────────────────────────────────────────────────────┤
│ ^Q Quit  ^D Verbose  ^F Files                                    │ Footer
└──────────────────────────────────────────────────────────────────┘
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Footer, RichLog

from galangal.ui.tui.adapters import PromptType, TUIAdapter
from galangal.ui.tui.modals import MultilineInputModal, PromptModal, PromptOption, TextInputModal
from galangal.ui.tui.widgets import (
    CurrentActionWidget,
    FilesPanelWidget,
    HeaderWidget,
    StageProgressWidget,
)


class WorkflowTUIApp(App):
    """Textual app for entire workflow execution with panels."""

    TITLE = "Galangal"

    CSS = """
    Screen {
        background: #282828;
    }

    #workflow-root {
        layout: grid;
        grid-size: 1;
        grid-rows: 2 2 1fr 1 auto;
        height: 100%;
        width: 100%;
    }

    #header {
        background: #3c3836;
        padding: 0 2;
        border-bottom: solid #504945;
        content-align: left middle;
    }

    #progress {
        background: #282828;
        padding: 0 2;
        content-align: center middle;
    }

    #main-content {
        layout: horizontal;
        height: 100%;
    }

    #activity-container {
        width: 75%;
        border-right: solid #504945;
        height: 100%;
    }

    #files-container {
        width: 25%;
        padding: 0 1;
        background: #1d2021;
        height: 100%;
    }

    #activity-log {
        background: #282828;
        scrollbar-color: #fe8019;
        scrollbar-background: #3c3836;
        height: 100%;
    }

    #current-action {
        background: #3c3836;
        padding: 0 2;
        border-top: solid #504945;
    }

    Footer {
        background: #1d2021;
    }

    Footer > .footer--key {
        background: #d3869b;
        color: #1d2021;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_workflow", "^Q Quit", show=True),
        Binding("ctrl+d", "toggle_verbose", "^D Verbose", show=True),
        Binding("ctrl+f", "toggle_files", "^F Files", show=True),
    ]

    def __init__(
        self,
        task_name: str,
        initial_stage: str,
        max_retries: int = 5,
        hidden_stages: frozenset = None,
    ):
        super().__init__()
        self.task_name = task_name
        self.current_stage = initial_stage
        self._max_retries = max_retries
        self._hidden_stages = hidden_stages or frozenset()
        self.verbose = False
        self._start_time = time.time()
        self._attempt = 1
        self._turns = 0

        # Raw lines storage for verbose replay
        self._raw_lines: list[str] = []
        self._activity_lines: list[tuple[str, str]] = []  # (icon, message)

        # Workflow control
        self._prompt_type = PromptType.NONE
        self._prompt_callback: Callable | None = None
        self._active_prompt_screen: PromptModal | None = None
        self._workflow_result: str | None = None
        self._paused = False

        # Text input state
        self._input_callback: Callable | None = None
        self._active_input_screen: TextInputModal | None = None
        self._files_visible = True

    def compose(self) -> ComposeResult:
        with Container(id="workflow-root"):
            yield HeaderWidget(id="header")
            yield StageProgressWidget(id="progress")
            with Horizontal(id="main-content"):
                with VerticalScroll(id="activity-container"):
                    yield RichLog(id="activity-log", highlight=True, markup=True)
                yield FilesPanelWidget(id="files-container")
            yield CurrentActionWidget(id="current-action")
            yield Footer()

    def on_mount(self) -> None:
        """Initialize widgets."""
        header = self.query_one("#header", HeaderWidget)
        header.task_name = self.task_name
        header.stage = self.current_stage
        header.attempt = self._attempt
        header.max_retries = self._max_retries

        progress = self.query_one("#progress", StageProgressWidget)
        progress.current_stage = self.current_stage
        progress.hidden_stages = self._hidden_stages

        # Start timers
        self.set_interval(1.0, self._update_elapsed)
        self.set_interval(0.1, self._update_spinner)

    def _update_elapsed(self) -> None:
        """Update elapsed time display."""
        elapsed = int(time.time() - self._start_time)
        if elapsed >= 3600:
            hours, remainder = divmod(elapsed, 3600)
            mins, secs = divmod(remainder, 60)
            elapsed_str = f"{hours}:{mins:02d}:{secs:02d}"
        else:
            mins, secs = divmod(elapsed, 60)
            elapsed_str = f"{mins}:{secs:02d}"

        try:
            header = self.query_one("#header", HeaderWidget)
            header.elapsed = elapsed_str
        except Exception:
            pass  # Widget may not exist during shutdown

    def _update_spinner(self) -> None:
        """Update action spinner."""
        try:
            action = self.query_one("#current-action", CurrentActionWidget)
            action.spinner_frame += 1
        except Exception:
            pass  # Widget may not exist during shutdown

    # -------------------------------------------------------------------------
    # Public API for workflow
    # -------------------------------------------------------------------------

    def update_stage(self, stage: str, attempt: int = 1) -> None:
        """Update current stage display."""
        self.current_stage = stage
        self._attempt = attempt

        def _update():
            header = self.query_one("#header", HeaderWidget)
            header.stage = stage
            header.attempt = attempt

            progress = self.query_one("#progress", StageProgressWidget)
            progress.current_stage = stage

        try:
            self.call_from_thread(_update)
        except Exception:
            _update()

    def set_status(self, status: str, detail: str = "") -> None:
        """Update current action display."""

        def _update():
            action = self.query_one("#current-action", CurrentActionWidget)
            action.action = status
            action.detail = detail

        try:
            self.call_from_thread(_update)
        except Exception:
            _update()

    def set_turns(self, turns: int) -> None:
        """Update turn count."""
        self._turns = turns

        def _update():
            header = self.query_one("#header", HeaderWidget)
            header.turns = turns

        try:
            self.call_from_thread(_update)
        except Exception:
            _update()

    def add_activity(self, activity: str, icon: str = "•") -> None:
        """Add activity to log."""
        # Store for replay when toggling modes
        self._activity_lines.append((icon, activity))

        def _add():
            # Only show activity in compact (non-verbose) mode
            if not self.verbose:
                log = self.query_one("#activity-log", RichLog)
                timestamp = datetime.now().strftime("%H:%M:%S")
                log.write(f"[#928374]{timestamp}[/] {icon} {activity}")

        try:
            self.call_from_thread(_add)
        except Exception:
            _add()

    def add_file(self, action: str, path: str) -> None:
        """Add file to files panel."""

        def _add():
            files = self.query_one("#files-container", FilesPanelWidget)
            files.add_file(action, path)

        try:
            self.call_from_thread(_add)
        except Exception:
            _add()

    def show_message(self, message: str, style: str = "info") -> None:
        """Show a styled message."""
        icons = {"info": "ℹ", "success": "✓", "error": "✗", "warning": "⚠"}
        colors = {"info": "#83a598", "success": "#b8bb26", "error": "#fb4934", "warning": "#fabd2f"}
        icon = icons.get(style, "•")
        color = colors.get(style, "#ebdbb2")
        self.add_activity(f"[{color}]{message}[/]", icon)

    def show_stage_complete(self, stage: str, success: bool) -> None:
        """Show stage completion."""
        if success:
            self.show_message(f"Stage {stage} completed", "success")
        else:
            self.show_message(f"Stage {stage} failed", "error")

    def show_workflow_complete(self) -> None:
        """Show workflow completion banner."""
        self.add_activity("")
        self.add_activity("[bold #b8bb26]════════════════════════════════════════[/]", "")
        self.add_activity("[bold #b8bb26]           WORKFLOW COMPLETE            [/]", "")
        self.add_activity("[bold #b8bb26]════════════════════════════════════════[/]", "")
        self.add_activity("")

    def show_prompt(self, prompt_type: PromptType, message: str, callback: Callable) -> None:
        """Show a prompt."""
        self._prompt_type = prompt_type
        self._prompt_callback = callback

        options = {
            PromptType.PLAN_APPROVAL: [
                PromptOption("1", "Approve", "yes", "#b8bb26"),
                PromptOption("2", "Reject", "no", "#fb4934"),
                PromptOption("3", "Quit", "quit", "#fabd2f"),
            ],
            PromptType.DESIGN_APPROVAL: [
                PromptOption("1", "Approve", "yes", "#b8bb26"),
                PromptOption("2", "Reject", "no", "#fb4934"),
                PromptOption("3", "Quit", "quit", "#fabd2f"),
            ],
            PromptType.COMPLETION: [
                PromptOption("1", "Create PR", "yes", "#b8bb26"),
                PromptOption("2", "Back to DEV", "no", "#fb4934"),
                PromptOption("3", "Quit", "quit", "#fabd2f"),
            ],
            PromptType.PREFLIGHT_RETRY: [
                PromptOption("1", "Retry", "retry", "#b8bb26"),
                PromptOption("2", "Quit", "quit", "#fb4934"),
            ],
            PromptType.STAGE_FAILURE: [
                PromptOption("1", "Retry", "retry", "#b8bb26"),
                PromptOption("2", "Fix in DEV", "fix_in_dev", "#fabd2f"),
                PromptOption("3", "Quit", "quit", "#fb4934"),
            ],
            PromptType.POST_COMPLETION: [
                PromptOption("1", "New Task", "new_task", "#b8bb26"),
                PromptOption("2", "Quit", "quit", "#fabd2f"),
            ],
            PromptType.TASK_TYPE: [
                PromptOption("1", "Feature - New functionality", "feature", "#b8bb26"),
                PromptOption("2", "Bug Fix - Fix broken behavior", "bugfix", "#fb4934"),
                PromptOption("3", "Refactor - Restructure code", "refactor", "#83a598"),
                PromptOption("4", "Chore - Dependencies, config", "chore", "#fabd2f"),
                PromptOption("5", "Docs - Documentation only", "docs", "#d3869b"),
                PromptOption("6", "Hotfix - Critical fix", "hotfix", "#fe8019"),
            ],
        }.get(
            prompt_type,
            [
                PromptOption("1", "Yes", "yes", "#b8bb26"),
                PromptOption("2", "No", "no", "#fb4934"),
                PromptOption("3", "Quit", "quit", "#fabd2f"),
            ],
        )

        def _show():
            try:

                def _handle(result: str | None) -> None:
                    self._active_prompt_screen = None
                    self._prompt_callback = None
                    self._prompt_type = PromptType.NONE
                    if result:
                        callback(result)

                screen = PromptModal(message, options)
                self._active_prompt_screen = screen
                self.push_screen(screen, _handle)
            except Exception as e:
                # Log error to activity - use internal method to avoid threading issues
                log = self.query_one("#activity-log", RichLog)
                log.write(f"[#fb4934]⚠ Prompt error: {e}[/]")

        try:
            self.call_from_thread(_show)
        except Exception:
            # Direct call as fallback
            _show()

    def hide_prompt(self) -> None:
        """Hide prompt."""
        self._prompt_type = PromptType.NONE
        self._prompt_callback = None

        def _hide():
            if self._active_prompt_screen:
                self._active_prompt_screen.dismiss(None)
                self._active_prompt_screen = None

        try:
            self.call_from_thread(_hide)
        except Exception:
            _hide()

    def show_text_input(self, label: str, default: str, callback: Callable) -> None:
        """Show text input prompt."""
        self._input_callback = callback

        def _show():
            try:

                def _handle(result: str | None) -> None:
                    self._active_input_screen = None
                    self._input_callback = None
                    callback(result if result else None)

                screen = TextInputModal(label, default)
                self._active_input_screen = screen
                self.push_screen(screen, _handle)
            except Exception as e:
                log = self.query_one("#activity-log", RichLog)
                log.write(f"[#fb4934]⚠ Input error: {e}[/]")

        try:
            self.call_from_thread(_show)
        except Exception:
            _show()

    def hide_text_input(self) -> None:
        """Reset text input prompt."""
        self._input_callback = None

        def _hide():
            if self._active_input_screen:
                self._active_input_screen.dismiss(None)
                self._active_input_screen = None

        try:
            self.call_from_thread(_hide)
        except Exception:
            _hide()

    def show_multiline_input(self, label: str, default: str, callback: Callable) -> None:
        """Show multiline text input prompt for task descriptions and briefs."""
        self._input_callback = callback

        def _show():
            try:

                def _handle(result: str | None) -> None:
                    self._active_input_screen = None
                    self._input_callback = None
                    callback(result if result else None)

                screen = MultilineInputModal(label, default)
                self._active_input_screen = screen
                self.push_screen(screen, _handle)
            except Exception as e:
                log = self.query_one("#activity-log", RichLog)
                log.write(f"[#fb4934]⚠ Input error: {e}[/]")

        try:
            self.call_from_thread(_show)
        except Exception:
            _show()

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def _text_input_active(self) -> bool:
        """Check if text input is currently active and should capture keys."""
        return self._input_callback is not None or self._active_input_screen is not None

    def check_action_quit_workflow(self) -> bool:
        return not self._text_input_active()

    def check_action_toggle_verbose(self) -> bool:
        return not self._text_input_active()

    def action_quit_workflow(self) -> None:
        if self._active_prompt_screen:
            self._active_prompt_screen.dismiss("quit")
            return
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("quit")
            return
        self._paused = True
        self._workflow_result = "paused"
        self.exit()

    def add_raw_line(self, line: str) -> None:
        """Store raw line and display if in verbose mode."""
        # Store for replay (keep last 500 lines)
        self._raw_lines.append(line)
        if len(self._raw_lines) > 500:
            self._raw_lines = self._raw_lines[-500:]

        def _add():
            if self.verbose:
                log = self.query_one("#activity-log", RichLog)
                display = line.strip()[:150]  # Truncate to 150 chars
                log.write(f"[#7c6f64]{display}[/]")

        try:
            self.call_from_thread(_add)
        except Exception:
            pass

    def action_toggle_verbose(self) -> None:
        self.verbose = not self.verbose
        log = self.query_one("#activity-log", RichLog)
        log.clear()

        if self.verbose:
            log.write("[#83a598]Switched to VERBOSE mode - showing raw JSON[/]")
            # Replay last 30 raw lines
            for line in self._raw_lines[-30:]:
                display = line.strip()[:150]
                log.write(f"[#7c6f64]{display}[/]")
        else:
            log.write("[#b8bb26]Switched to COMPACT mode[/]")
            # Replay recent activity
            for icon, activity in self._activity_lines[-30:]:
                log.write(f"  {icon} {activity}")

    def action_toggle_files(self) -> None:
        self._files_visible = not self._files_visible
        files = self.query_one("#files-container", FilesPanelWidget)
        activity = self.query_one("#activity-container", VerticalScroll)

        if self._files_visible:
            files.display = True
            files.styles.width = "25%"
            activity.styles.width = "75%"
        else:
            files.display = False
            activity.styles.width = "100%"


class StageTUIApp(WorkflowTUIApp):
    """Single-stage TUI app."""

    def __init__(
        self,
        task_name: str,
        stage: str,
        branch: str,
        attempt: int,
        prompt: str,
    ):
        super().__init__(task_name, stage)
        self.branch = branch
        self._attempt = attempt
        self.prompt = prompt
        self.result: tuple[bool, str] = (False, "")

    def on_mount(self) -> None:
        super().on_mount()
        self._worker_thread = threading.Thread(target=self._execute_stage, daemon=True)
        self._worker_thread.start()

    def _execute_stage(self) -> None:
        from galangal.ai.claude import ClaudeBackend

        backend = ClaudeBackend()
        ui = TUIAdapter(self)

        self.result = backend.invoke(
            prompt=self.prompt,
            timeout=14400,
            max_turns=200,
            ui=ui,
        )

        success, _ = self.result
        if success:
            self.call_from_thread(self.add_activity, "[#b8bb26]Stage completed[/]", "✓")
        else:
            self.call_from_thread(self.add_activity, "[#fb4934]Stage failed[/]", "✗")

        self.call_from_thread(self.set_timer, 1.5, self.exit)
