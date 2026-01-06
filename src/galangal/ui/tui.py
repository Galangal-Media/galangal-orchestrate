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
│ q Quit  v Verbose  y Yes  n No                                   │ Footer
└──────────────────────────────────────────────────────────────────┘
"""

import threading
import time
from datetime import datetime
from typing import Optional, Callable
from enum import Enum

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Static, RichLog, Input
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.reactive import reactive

from galangal.ai.claude import ClaudeBackend
from galangal.core.state import Stage, STAGE_ORDER


class PromptType(Enum):
    """Types of prompts the TUI can show."""
    NONE = "none"
    PLAN_APPROVAL = "plan_approval"
    DESIGN_APPROVAL = "design_approval"
    COMPLETION = "completion"
    TEXT_INPUT = "text_input"


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

    def render(self) -> Text:
        text = Text(justify="center")

        try:
            current_idx = next(
                i for i, s in enumerate(STAGE_ORDER)
                if s.value == self.current_stage
            )
        except StopIteration:
            current_idx = 0

        for i, stage in enumerate(STAGE_ORDER):
            if i > 0:
                text.append(" ━ ", style="#504945")

            name = self.STAGE_DISPLAY.get(stage.value, stage.value)

            if stage.value in self.skipped_stages:
                text.append(f"⊘ {name}", style="#504945 strike")
            elif i < current_idx:
                text.append(f"● {name}", style="#b8bb26")
            elif i == current_idx:
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
                detail = self.detail[:150] + "..." if len(self.detail) > 150 else self.detail
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
        # Shorten path for display
        if "/" in path:
            parts = path.split("/")
            short_path = parts[-1]
            if len(short_path) > 25:
                short_path = short_path[:22] + "..."
        else:
            short_path = path[:25] if len(path) > 25 else path

        entry = (action, short_path)
        if entry not in self._files:
            self._files.append(entry)
            self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("Files\n", style="bold #928374")
        text.append("─" * 20 + "\n", style="#504945")

        if not self._files:
            text.append("(none yet)", style="#504945 italic")
        else:
            # Show last 20 files
            for action, path in self._files[-20:]:
                icon = "✏️" if action == "write" else "📖"
                color = "#b8bb26" if action == "write" else "#83a598"
                text.append(f"{icon} ", style=color)
                text.append(f"{path}\n", style="#ebdbb2")

        return text


class PromptWidget(Static):
    """Widget for showing prompts."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._message = ""
        self._options = ""
        self._visible = False
        self.display = False  # Hidden by default

    def set_prompt(self, message: str, options: str) -> None:
        """Set prompt content and show it."""
        self._message = message
        self._options = options
        self._visible = True
        self.display = True  # Show widget in layout
        self.refresh()

    def hide(self) -> None:
        """Hide the prompt."""
        self._visible = False
        self._message = ""
        self._options = ""
        self.display = False  # Remove from layout
        self.refresh()

    def render(self) -> Text:
        if not self._visible or not self._message:
            return Text("")

        text = Text()
        text.append("\n", style="")
        text.append("─" * 70 + "\n", style="#504945")
        text.append("  " + self._message + "\n", style="bold #ebdbb2")
        text.append("  ")
        # Parse Rich markup for options (contains color codes)
        text.append_text(Text.from_markup(self._options))
        text.append("\n")
        text.append("─" * 70, style="#504945")
        return text


class InputPromptWidget(Static):
    """Widget for text input prompts."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._label = ""
        self._visible = False
        self.display = False

    def show_input(self, label: str, default: str = "") -> None:
        """Show input prompt with label."""
        self._label = label
        self._visible = True
        self.display = True
        self.refresh()

    def hide(self) -> None:
        """Hide the input prompt."""
        self._visible = False
        self._label = ""
        self.display = False
        self.refresh()

    def render(self) -> Text:
        if not self._visible:
            return Text("")

        text = Text()
        text.append("─" * 70 + "\n", style="#504945")
        text.append("  " + self._label + "\n", style="bold #ebdbb2")
        text.append("  [#928374]Press Enter to submit, Escape to cancel[/]\n", style="")
        text.append("─" * 70, style="#504945")
        return Text.from_markup(str(text))


# =============================================================================
# Main TUI App
# =============================================================================


class WorkflowTUIApp(App):
    """Textual app for entire workflow execution with panels."""

    TITLE = "Galangal"

    CSS = """
    Screen {
        background: #282828;
        layout: grid;
        grid-size: 1;
        grid-rows: 2 2 1fr 1 auto;
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

    #prompt-area {
        background: #3c3836;
        padding: 0 2;
        height: auto;
    }

    #input-label {
        background: #3c3836;
        padding: 0 2;
        height: auto;
    }

    #input-container {
        height: 3;
        padding: 0 2;
        background: #3c3836;
    }

    #text-input {
        width: 100%;
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
        Binding("y", "select_yes", "Yes", show=False),
        Binding("n", "select_no", "No", show=False),
        Binding("1", "select_option_1", "1", show=False),
        Binding("2", "select_option_2", "2", show=False),
        Binding("3", "select_option_3", "3", show=False),
    ]

    def __init__(self, task_name: str, initial_stage: str, max_retries: int = 5):
        super().__init__()
        self.task_name = task_name
        self.current_stage = initial_stage
        self._max_retries = max_retries
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
        self._workflow_result: Optional[str] = None
        self._paused = False

        # Text input state
        self._input_callback: Optional[Callable] = None
        self._input_label = ""

    def compose(self) -> ComposeResult:
        yield HeaderWidget(id="header")
        yield StageProgressWidget(id="progress")
        with Horizontal(id="main-content"):
            with VerticalScroll(id="activity-container"):
                yield RichLog(id="activity-log", highlight=True, markup=True)
            yield FilesPanelWidget(id="files-container")
        yield CurrentActionWidget(id="current-action")
        yield PromptWidget(id="prompt-area")
        yield InputPromptWidget(id="input-label")
        with Container(id="input-container"):
            yield Input(id="text-input", placeholder="Type message to AI...")
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

        # Hide input label by default (but keep input always visible)
        self.query_one("#input-label", InputPromptWidget).display = False

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

        options_text = {
            PromptType.PLAN_APPROVAL: "[#b8bb26]1[/] Approve  [#fb4934]2[/] Reject  [#fabd2f]3[/] Quit",
            PromptType.DESIGN_APPROVAL: "[#b8bb26]1[/] Approve  [#fb4934]2[/] Reject  [#fabd2f]3[/] Quit",
            PromptType.COMPLETION: "[#b8bb26]1[/] Create PR  [#fb4934]2[/] Back to DEV  [#fabd2f]3[/] Quit",
        }.get(prompt_type, "[#b8bb26]1[/] Yes  [#fb4934]2[/] No  [#fabd2f]3[/] Quit")

        # Store for use in _show closure
        msg = message
        opts = options_text

        def _show():
            try:
                prompt = self.query_one("#prompt-area", PromptWidget)
                prompt.set_prompt(msg, opts)
            except Exception as e:
                # Log error to activity - use internal method to avoid threading issues
                log = self.query_one("#activity-log", RichLog)
                log.write(f"[#fb4934]⚠ Prompt error: {e}[/]")

        try:
            self.call_from_thread(_show)
        except Exception:
            # Direct call as fallback
            try:
                prompt = self.query_one("#prompt-area", PromptWidget)
                prompt.set_prompt(msg, opts)
            except Exception:
                pass

    def hide_prompt(self) -> None:
        """Hide prompt."""
        self._prompt_type = PromptType.NONE
        self._prompt_callback = None

        def _hide():
            prompt = self.query_one("#prompt-area", PromptWidget)
            prompt.hide()

        try:
            self.call_from_thread(_hide)
        except Exception:
            try:
                prompt = self.query_one("#prompt-area", PromptWidget)
                prompt.hide()
            except Exception:
                pass

    def show_text_input(self, label: str, default: str, callback: Callable) -> None:
        """Show text input prompt."""
        self._input_callback = callback
        self._input_label = label

        def _show():
            try:
                input_label = self.query_one("#input-label", InputPromptWidget)
                input_label.show_input(label)

                text_input = self.query_one("#text-input", Input)
                text_input.value = default
                text_input.placeholder = label
                self.set_focus(text_input)
                text_input.cursor_position = len(default)
            except Exception as e:
                log = self.query_one("#activity-log", RichLog)
                log.write(f"[#fb4934]⚠ Input error: {e}[/]")

        try:
            self.call_from_thread(_show)
        except Exception:
            try:
                input_label = self.query_one("#input-label", InputPromptWidget)
                input_label.show_input(label)
                text_input = self.query_one("#text-input", Input)
                text_input.value = default
                text_input.placeholder = label
                self.set_focus(text_input)
                text_input.cursor_position = len(default)
            except Exception:
                pass

    def hide_text_input(self) -> None:
        """Reset text input prompt."""
        self._input_callback = None
        self._input_label = ""

        def _hide():
            try:
                input_label = self.query_one("#input-label", InputPromptWidget)
                input_label.hide()
                text_input = self.query_one("#text-input", Input)
                text_input.value = ""
                text_input.placeholder = "Type message to AI..."
            except Exception:
                pass

        try:
            self.call_from_thread(_hide)
        except Exception:
            try:
                self.query_one("#input-label", InputPromptWidget).hide()
                text_input = self.query_one("#text-input", Input)
                text_input.value = ""
                text_input.placeholder = "Type message to AI..."
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle text input submission."""
        if self._input_callback and event.input.id == "text-input":
            callback = self._input_callback
            value = event.value.strip()
            self.hide_text_input()
            callback(value if value else None)

    def on_key(self, event) -> None:
        """Handle escape key to cancel text input."""
        if event.key == "escape" and self._input_callback:
            callback = self._input_callback
            self.hide_text_input()
            callback(None)  # None indicates cancelled

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def _text_input_active(self) -> bool:
        """Check if text input is currently active and should capture keys."""
        return self._input_callback is not None

    # Check methods - return False to skip binding and let Input widget handle key
    def check_action_select_yes(self) -> bool:
        return not self._text_input_active()

    def check_action_select_no(self) -> bool:
        return not self._text_input_active()

    def check_action_quit_workflow(self) -> bool:
        return not self._text_input_active()

    def check_action_select_option_1(self) -> bool:
        return not self._text_input_active()

    def check_action_select_option_2(self) -> bool:
        return not self._text_input_active()

    def check_action_select_option_3(self) -> bool:
        return not self._text_input_active()

    def check_action_toggle_verbose(self) -> bool:
        return not self._text_input_active()

    def action_select_yes(self) -> None:
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("yes")

    def action_select_no(self) -> None:
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("no")

    def action_quit_workflow(self) -> None:
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("quit")
        else:
            self._paused = True
            self._workflow_result = "paused"
            self.exit()

    def action_select_option_1(self) -> None:
        """Handle option 1 (Approve/Yes)."""
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("yes")

    def action_select_option_2(self) -> None:
        """Handle option 2 (Reject/No)."""
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("no")

    def action_select_option_3(self) -> None:
        """Handle option 3 (Quit)."""
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("quit")
        else:
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
