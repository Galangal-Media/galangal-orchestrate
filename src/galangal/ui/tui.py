"""
Textual TUI for workflow execution display.

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
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable
from enum import Enum

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Static, RichLog, Input
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.reactive import reactive
from textual.screen import ModalScreen

from galangal.ai.claude import ClaudeBackend
from galangal.core.state import Stage, STAGE_ORDER


class PromptType(Enum):
    """Types of prompts the TUI can show."""
    NONE = "none"
    PLAN_APPROVAL = "plan_approval"
    DESIGN_APPROVAL = "design_approval"
    COMPLETION = "completion"
    TEXT_INPUT = "text_input"
    PREFLIGHT_RETRY = "preflight_retry"
    STAGE_FAILURE = "stage_failure"


class StageUI:
    """Interface for stage execution UI updates."""

    def set_status(self, status: str, detail: str = "") -> None:
        pass

    def add_activity(self, activity: str, icon: str = "•") -> None:
        pass

    def add_raw_line(self, line: str) -> None:
        pass

    def set_turns(self, turns: int) -> None:
        pass

    def finish(self, success: bool) -> None:
        pass


# =============================================================================
# Custom Widgets
# =============================================================================


class HeaderWidget(Static):
    """Fixed header showing task info."""

    task_name: reactive[str] = reactive("")
    stage: reactive[str] = reactive("")
    attempt: reactive[int] = reactive(1)
    max_retries: reactive[int] = reactive(5)
    elapsed: reactive[str] = reactive("0:00")
    turns: reactive[int] = reactive(0)
    status: reactive[str] = reactive("starting")

    def render(self) -> Text:
        text = Text()

        # Row 1: Task, Stage, Attempt
        text.append("Task: ", style="#928374")
        text.append(self.task_name[:30], style="bold #83a598")
        text.append("  Stage: ", style="#928374")
        text.append(f"{self.stage}", style="bold #fabd2f")
        text.append(f" ({self.attempt}/{self.max_retries})", style="#928374")
        text.append("  Elapsed: ", style="#928374")
        text.append(self.elapsed, style="bold #ebdbb2")
        text.append("  Turns: ", style="#928374")
        text.append(str(self.turns), style="bold #b8bb26")

        return text


class StageProgressWidget(Static):
    """Centered stage progress bar with full names."""

    current_stage: reactive[str] = reactive("PM")
    skipped_stages: reactive[frozenset] = reactive(frozenset())
    hidden_stages: reactive[frozenset] = reactive(frozenset())

    # Full stage display names
    STAGE_DISPLAY = {
        "PM": "PM",
        "DESIGN": "DESIGN",
        "PREFLIGHT": "PREFLIGHT",
        "DEV": "DEV",
        "MIGRATION": "MIGRATION",
        "TEST": "TEST",
        "CONTRACT": "CONTRACT",
        "QA": "QA",
        "BENCHMARK": "BENCHMARK",
        "SECURITY": "SECURITY",
        "REVIEW": "REVIEW",
        "DOCS": "DOCS",
        "COMPLETE": "COMPLETE",
    }

    STAGE_COMPACT = {
        "PM": "PM",
        "DESIGN": "DSGN",
        "PREFLIGHT": "PREF",
        "DEV": "DEV",
        "MIGRATION": "MIGR",
        "TEST": "TEST",
        "CONTRACT": "CNTR",
        "QA": "QA",
        "BENCHMARK": "BENCH",
        "SECURITY": "SEC",
        "REVIEW": "RVW",
        "DOCS": "DOCS",
        "COMPLETE": "DONE",
    }

    def render(self) -> Text:
        text = Text(justify="center")

        # Filter out hidden stages (task type + config skips)
        visible_stages = [s for s in STAGE_ORDER if s.value not in self.hidden_stages]

        try:
            current_idx = next(
                i for i, s in enumerate(visible_stages)
                if s.value == self.current_stage
            )
        except StopIteration:
            current_idx = 0

        width = self.size.width or 0
        use_window = width and width < 70
        use_compact = width and width < 110
        display_names = self.STAGE_COMPACT if use_compact else self.STAGE_DISPLAY

        stages = visible_stages
        if use_window:
            start = max(current_idx - 2, 0)
            end = min(current_idx + 3, len(stages))
            items: list[Optional[int]] = []
            if start > 0:
                items.append(None)
            items.extend(range(start, end))
            if end < len(stages):
                items.append(None)
        else:
            items = list(range(len(stages)))

        for idx, stage_idx in enumerate(items):
            if idx > 0:
                text.append(" ━ ", style="#504945")
            if stage_idx is None:
                text.append("...", style="#504945")
                continue

            stage = stages[stage_idx]
            name = display_names.get(stage.value, stage.value)

            if stage.value in self.skipped_stages:
                text.append(f"⊘ {name}", style="#504945 strike")
            elif stage_idx < current_idx:
                text.append(f"● {name}", style="#b8bb26")
            elif stage_idx == current_idx:
                text.append(f"◉ {name}", style="bold #fabd2f")
            else:
                text.append(f"○ {name}", style="#504945")

        return text


class CurrentActionWidget(Static):
    """Shows the current action with animated spinner."""

    action: reactive[str] = reactive("")
    detail: reactive[str] = reactive("")
    spinner_frame: reactive[int] = reactive(0)

    SPINNERS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def render(self) -> Text:
        text = Text()
        if self.action:
            spinner = self.SPINNERS[self.spinner_frame % len(self.SPINNERS)]
            text.append(f"{spinner} ", style="#83a598")
            text.append(self.action, style="bold #ebdbb2")
            if self.detail:
                detail = self.detail
                width = self.size.width or 0
                if width:
                    reserved = len(self.action) + 4
                    max_detail = max(width - reserved, 0)
                    if max_detail and len(detail) > max_detail:
                        if max_detail > 3:
                            detail = detail[: max_detail - 3] + "..."
                        else:
                            detail = ""
                if not detail:
                    return text
                text.append(f": {detail}", style="#928374")
        else:
            text.append("○ Idle", style="#504945")
        return text


class FilesPanelWidget(Static):
    """Panel showing files that have been read/written."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._files: list[tuple[str, str]] = []

    def add_file(self, action: str, path: str) -> None:
        """Add a file operation."""
        entry = (action, path)
        if entry not in self._files:
            self._files.append(entry)
            self.refresh()

    def render(self) -> Text:
        width = self.size.width or 24
        divider_width = max(width - 1, 1)
        text = Text()
        text.append("Files\n", style="bold #928374")
        text.append("─" * divider_width + "\n", style="#504945")

        if not self._files:
            text.append("(none yet)", style="#504945 italic")
        else:
            # Show last 20 files
            for action, path in self._files[-20:]:
                display_path = path
                if "/" in display_path:
                    parts = display_path.split("/")
                    display_path = "/".join(parts[-2:])
                max_len = max(width - 4, 1)
                if len(display_path) > max_len:
                    if max_len > 3:
                        display_path = display_path[: max_len - 3] + "..."
                    else:
                        display_path = display_path[:max_len]
                icon = "✏️" if action == "write" else "📖"
                color = "#b8bb26" if action == "write" else "#83a598"
                text.append(f"{icon} ", style=color)
                text.append(f"{display_path}\n", style="#ebdbb2")

        return text


# =============================================================================
# Prompt Modal
# =============================================================================


@dataclass(frozen=True)
class PromptOption:
    key: str
    label: str
    result: str
    color: str


class PromptModal(ModalScreen):
    """Modal prompt for multi-choice selections."""

    CSS = """
    PromptModal {
        align: center middle;
        layout: vertical;
    }

    #prompt-dialog {
        width: 90%;
        max-width: 120;
        min-width: 50;
        max-height: 80%;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
        overflow-y: auto;
    }

    #prompt-message {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        text-wrap: wrap;
    }

    #prompt-options {
        color: #ebdbb2;
    }

    #prompt-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("1", "choose_1", show=False),
        Binding("2", "choose_2", show=False),
        Binding("3", "choose_3", show=False),
        Binding("y", "choose_yes", show=False),
        Binding("n", "choose_no", show=False),
        Binding("q", "choose_quit", show=False),
        Binding("escape", "choose_quit", show=False),
    ]

    def __init__(self, message: str, options: list[PromptOption]):
        super().__init__()
        self._message = message
        self._options = options
        self._key_map = {option.key: option.result for option in options}

    def compose(self) -> ComposeResult:
        options_text = "\n".join(
            f"[{option.color}]{option.key}[/] {option.label}" for option in self._options
        )
        with Vertical(id="prompt-dialog"):
            yield Static(self._message, id="prompt-message")
            yield Static(Text.from_markup(options_text), id="prompt-options")
            yield Static("Press 1-3 to choose, Esc to cancel", id="prompt-hint")

    def _submit_key(self, key: str) -> None:
        result = self._key_map.get(key)
        if result:
            self.dismiss(result)

    def action_choose_1(self) -> None:
        self._submit_key("1")

    def action_choose_2(self) -> None:
        self._submit_key("2")

    def action_choose_3(self) -> None:
        self._submit_key("3")

    def action_choose_yes(self) -> None:
        self.dismiss("yes")

    def action_choose_no(self) -> None:
        self.dismiss("no")

    def action_choose_quit(self) -> None:
        self.dismiss("quit")


# =============================================================================
# Text Input Modal
# =============================================================================


class TextInputModal(ModalScreen):
    """Modal for collecting short text input."""

    CSS = """
    TextInputModal {
        align: center middle;
        layout: vertical;
    }

    #text-input-dialog {
        width: 70%;
        max-width: 80;
        min-width: 40;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
    }

    #text-input-label {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        text-wrap: wrap;
    }

    #text-input-field {
        width: 100%;
    }

    #text-input-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    def __init__(self, label: str, default: str = ""):
        super().__init__()
        self._label = label
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="text-input-dialog"):
            yield Static(self._label, id="text-input-label")
            yield Input(value=self._default, placeholder=self._label, id="text-input-field")
            yield Static("Press Enter to submit, Esc to cancel", id="text-input-hint")

    def on_mount(self) -> None:
        field = self.query_one("#text-input-field", Input)
        self.set_focus(field)
        field.cursor_position = len(field.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "text-input-field":
            value = event.value.strip()
            self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# =============================================================================
# Main TUI App
# =============================================================================


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
        self._prompt_callback: Optional[Callable] = None
        self._active_prompt_screen: Optional[PromptModal] = None
        self._workflow_result: Optional[str] = None
        self._paused = False

        # Text input state
        self._input_callback: Optional[Callable] = None
        self._active_input_screen: Optional[TextInputModal] = None
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

        header = self.query_one("#header", HeaderWidget)
        header.elapsed = elapsed_str

    def _update_spinner(self) -> None:
        """Update action spinner."""
        action = self.query_one("#current-action", CurrentActionWidget)
        action.spinner_frame += 1

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
        }.get(prompt_type, [
            PromptOption("1", "Yes", "yes", "#b8bb26"),
            PromptOption("2", "No", "no", "#fb4934"),
            PromptOption("3", "Quit", "quit", "#fabd2f"),
        ])

        def _show():
            try:
                def _handle(result: Optional[str]) -> None:
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
                def _handle(result: Optional[str]) -> None:
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


# =============================================================================
# TUI Adapter for ClaudeBackend
# =============================================================================


class TUIAdapter(StageUI):
    """Adapter to connect ClaudeBackend to TUI."""

    def __init__(self, app: WorkflowTUIApp):
        self.app = app

    def set_status(self, status: str, detail: str = "") -> None:
        self.app.set_status(status, detail)

    def add_activity(self, activity: str, icon: str = "•") -> None:
        self.app.add_activity(activity, icon)

        # Track file operations
        if "Read:" in activity or "📖" in activity:
            path = activity.split(":")[-1].strip() if ":" in activity else activity
            self.app.add_file("read", path)
        elif "Edit:" in activity or "Write:" in activity or "✏️" in activity:
            path = activity.split(":")[-1].strip() if ":" in activity else activity
            self.app.add_file("write", path)

    def add_raw_line(self, line: str) -> None:
        """Pass raw line to app for storage and display."""
        self.app.add_raw_line(line)

    def set_turns(self, turns: int) -> None:
        self.app.set_turns(turns)

    def finish(self, success: bool) -> None:
        pass


# =============================================================================
# Simple Console UI (fallback)
# =============================================================================


class SimpleConsoleUI(StageUI):
    """Simple console-based UI without Textual."""

    def __init__(self, task_name: str, stage: str):
        from rich.console import Console
        self.console = Console()
        self.task_name = task_name
        self.stage = stage
        self.turns = 0

    def set_status(self, status: str, detail: str = "") -> None:
        self.console.print(f"[dim]{status}: {detail}[/dim]")

    def add_activity(self, activity: str, icon: str = "•") -> None:
        self.console.print(f"  {icon} {activity}")

    def add_raw_line(self, line: str) -> None:
        pass

    def set_turns(self, turns: int) -> None:
        self.turns = turns
        self.console.print(f"[dim]Turn {turns}[/dim]")

    def finish(self, success: bool) -> None:
        if success:
            self.console.print(f"[green]✓ {self.stage} completed[/green]")
        else:
            self.console.print(f"[red]✗ {self.stage} failed[/red]")


# =============================================================================
# Legacy single-stage TUI (backward compatible)
# =============================================================================


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


# =============================================================================
# Entry Points
# =============================================================================


def _run_simple_mode(
    task_name: str,
    stage: str,
    attempt: int,
    prompt: str,
) -> tuple[bool, str]:
    """Run stage without TUI."""
    from rich.console import Console
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
    import os

    if os.environ.get("GALANGAL_NO_TUI"):
        return _run_simple_mode(task_name, stage, attempt, prompt)

    try:
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
