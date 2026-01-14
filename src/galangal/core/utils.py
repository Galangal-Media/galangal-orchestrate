"""
Common utility functions to avoid code duplication.
"""

import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Debug mode is enabled via GALANGAL_DEBUG environment variable
_debug_enabled: bool | None = None
_debug_file: Path | None = None


def is_debug_enabled() -> bool:
    """Check if debug mode is enabled.

    Note: This always checks the environment variable (no caching) to handle
    cases where debug mode is enabled after initial import.
    """
    return os.environ.get("GALANGAL_DEBUG", "").lower() in ("1", "true", "yes")


def reset_debug_state() -> None:
    """Reset debug state. Called when debug mode is enabled via CLI."""
    global _debug_enabled, _debug_file
    _debug_enabled = None
    _debug_file = None


def debug_log(message: str, **context) -> None:
    """Log a debug message if debug mode is enabled.

    Writes to logs/galangal_debug.log with timestamp.

    Args:
        message: The message to log.
        **context: Additional key-value pairs to include in the log.

    Example:
        debug_log("GitHub API call failed", error=str(e), issue=123)
    """
    if not is_debug_enabled():
        return

    global _debug_file
    if _debug_file is None:
        logs_dir = Path.cwd() / "logs"
        logs_dir.mkdir(exist_ok=True)
        _debug_file = logs_dir / "galangal_debug.log"

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    context_str = " ".join(f"{k}={v}" for k, v in context.items()) if context else ""
    line = f"[{timestamp}] {message}"
    if context_str:
        line += f" | {context_str}"

    try:
        with open(_debug_file, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Don't fail if we can't write debug log


def debug_exception(message: str, exc: Exception) -> None:
    """Log an exception with full traceback if debug mode is enabled.

    Args:
        message: Context message about what failed.
        exc: The exception that was caught.
    """
    if not is_debug_enabled():
        return

    debug_log(f"{message}: {type(exc).__name__}: {exc}")
    debug_log(f"Traceback:\n{traceback.format_exc()}")


def now_iso() -> str:
    """Return current UTC datetime as ISO format string.

    This is the canonical way to get timestamps throughout the codebase.

    Returns:
        ISO format string, e.g., "2024-01-15T10:30:00+00:00"
    """
    return datetime.now(timezone.utc).isoformat()


def now_formatted() -> str:
    """Return current UTC datetime in human-readable format.

    Returns:
        Formatted string, e.g., "2024-01-15 10:30 UTC"
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def truncate_text(
    text: str,
    max_length: int = 1500,
    suffix: str = "...",
) -> str:
    """Truncate text to max_length, adding suffix if truncated.

    Args:
        text: Text to truncate.
        max_length: Maximum length before truncation.
        suffix: String to append if truncated.

    Returns:
        Original text if within limit, or truncated text with suffix.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + suffix
