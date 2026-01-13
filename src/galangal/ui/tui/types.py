"""
Activity log types for structured logging.

Provides structured activity entries with level, category, and optional details
for filtering and export capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class ActivityLevel(str, Enum):
    """Log entry severity level."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class ActivityCategory(str, Enum):
    """Log entry category for filtering."""

    STAGE = "stage"  # Stage transitions
    VALIDATION = "validation"  # Validation results
    CLAUDE = "claude"  # AI backend activity
    FILE = "file"  # File operations
    SYSTEM = "system"  # System messages


def _get_display_width(char: str) -> int:
    """
    Get the display width of a character in terminal cells.

    Most emojis are 2 cells wide, while ASCII and Unicode symbols are 1 cell.
    This is a simplified heuristic that works for common icons.

    Args:
        char: Single character or short string.

    Returns:
        Display width in terminal cells (1 or 2).
    """
    if not char:
        return 0

    # Get the first character's code point
    cp = ord(char[0])

    # Emojis in common ranges are typically 2 cells wide
    # - Miscellaneous Symbols and Pictographs: U+1F300-U+1F5FF
    # - Emoticons: U+1F600-U+1F64F
    # - Transport and Map Symbols: U+1F680-U+1F6FF
    # - Supplemental Symbols: U+1F900-U+1F9FF
    # - Symbols and Pictographs Extended-A: U+1FA00-U+1FAFF
    if cp >= 0x1F300:
        return 2

    # Variation selector sequences (emoji with ️) - check for VS16
    if len(char) > 1 and ord(char[-1]) == 0xFE0F:
        return 2

    # Everything else (ASCII, Unicode symbols like ✓✗⚠ℹ) is 1 cell
    return 1


@dataclass
class ActivityEntry:
    """
    Structured activity log entry.

    Captures rich metadata about each activity for filtering,
    display, and export purposes.

    Attributes:
        timestamp: When the activity occurred (UTC).
        level: Severity level (info, success, warning, error).
        category: Category for filtering (stage, validation, claude, file, system).
        message: Human-readable message.
        icon: Display icon for the entry.
        details: Optional additional details (e.g., stack trace, full output).
    """

    message: str
    level: ActivityLevel = ActivityLevel.INFO
    category: ActivityCategory = ActivityCategory.SYSTEM
    icon: str = "•"
    details: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def format_display(self, show_timestamp: bool = True) -> str:
        """
        Format entry for display in TUI.

        Args:
            show_timestamp: Whether to include timestamp prefix.

        Returns:
            Formatted string with Rich markup.
        """
        colors = {
            ActivityLevel.INFO: "#ebdbb2",
            ActivityLevel.SUCCESS: "#b8bb26",
            ActivityLevel.WARNING: "#fabd2f",
            ActivityLevel.ERROR: "#fb4934",
        }
        color = colors.get(self.level, "#ebdbb2")

        # Normalize icon to consistent 2-cell width for alignment
        # Emojis are 2 cells, Unicode symbols and ASCII are 1 cell
        icon = self.icon if self.icon else " "
        icon_width = _get_display_width(icon)
        # Pad to 2 cells + 1 separator space
        icon_display = icon + " " * (3 - icon_width)

        if show_timestamp:
            time_str = self.timestamp.strftime("%H:%M:%S")
            return f"[#928374]{time_str}[/] {icon_display}[{color}]{self.message}[/]"
        return f"{icon_display}[{color}]{self.message}[/]"

    def format_export(self) -> str:
        """
        Format entry for file export (plain text).

        Returns:
            Plain text line suitable for log file.
        """
        time_str = self.timestamp.isoformat()
        line = f"{time_str} [{self.level.value}] [{self.category.value}] {self.message}"
        if self.details:
            line += f"\n  {self.details}"
        return line


def export_activity_log(entries: list[ActivityEntry], path: Path) -> None:
    """
    Export activity log entries to a file.

    Args:
        entries: List of activity entries to export.
        path: File path to write to.
    """
    with open(path, "w") as f:
        f.write("# Activity Log Export\n")
        f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# Entries: {len(entries)}\n\n")
        for entry in entries:
            f.write(entry.format_export() + "\n")
