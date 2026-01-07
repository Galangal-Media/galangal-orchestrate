"""
Custom Textual widgets for TUI display.
"""

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from galangal.core.state import STAGE_ORDER


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
            items: list[int | None] = []
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
