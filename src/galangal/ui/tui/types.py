"""
Activity log types for structured logging.

Provides structured activity entries with level, category, and optional details
for filtering and export capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal


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

        if show_timestamp:
            time_str = self.timestamp.strftime("%H:%M:%S")
            return f"[#928374]{time_str}[/] {self.icon} [{color}]{self.message}[/]"
        return f"{self.icon} [{color}]{self.message}[/]"

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
        f.write(f"# Activity Log Export\n")
        f.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# Entries: {len(entries)}\n\n")
        for entry in entries:
            f.write(entry.format_export() + "\n")
