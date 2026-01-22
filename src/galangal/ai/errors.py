"""
Error classification and remediation suggestions for AI backend failures.

Provides structured error analysis with actionable suggestions to help users
resolve common issues without digging through logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class ErrorCategory(Enum):
    """Categories of AI backend errors."""

    AUTH = auto()  # Authentication issues
    NETWORK = auto()  # Network/connectivity issues
    TIMEOUT = auto()  # Operation timed out
    RATE_LIMIT = auto()  # Rate limiting
    CLI_NOT_FOUND = auto()  # CLI tool not installed
    PERMISSION = auto()  # File/directory permissions
    CONFIG = auto()  # Configuration issues
    MAX_TURNS = auto()  # Max turns exceeded
    UNKNOWN = auto()  # Unclassified error


@dataclass
class ErrorContext:
    """Structured error context with classification and suggestions."""

    category: ErrorCategory
    message: str
    details: str | None = None
    suggestions: list[str] = field(default_factory=list)
    exit_code: int | None = None
    last_output_lines: list[str] = field(default_factory=list)

    def format_for_display(self) -> str:
        """Format error for terminal display with Rich markup."""
        lines = [f"[#fb4934 bold]{self.message}[/]"]

        if self.exit_code is not None:
            lines.append(f"\n[#7c6f64]Exit code:[/] {self.exit_code}")

        if self.last_output_lines:
            lines.append("\n[#7c6f64]Last output:[/]")
            for line in self.last_output_lines[-5:]:  # Last 5 lines
                # Truncate long lines
                display_line = line[:200] + "..." if len(line) > 200 else line
                lines.append(f"  [#a89984]> {display_line}[/]")

        if self.suggestions:
            lines.append("\n[#fabd2f]Suggestions:[/]")
            for i, suggestion in enumerate(self.suggestions, 1):
                lines.append(f"  {i}. {suggestion}")

        return "\n".join(lines)

    def format_for_log(self) -> str:
        """Format error for plain text logging."""
        lines = [self.message]

        if self.exit_code is not None:
            lines.append(f"Exit code: {self.exit_code}")

        if self.details:
            lines.append(f"Details: {self.details}")

        if self.last_output_lines:
            lines.append("Last output:")
            for line in self.last_output_lines[-5:]:
                lines.append(f"  > {line[:200]}")

        if self.suggestions:
            lines.append("Suggestions:")
            for i, suggestion in enumerate(self.suggestions, 1):
                lines.append(f"  {i}. {suggestion}")

        return "\n".join(lines)


# Error patterns and their classifications
_AUTH_PATTERNS = [
    "authentication required",
    "auth login",
    "not authenticated",
    "unauthorized",
    "401",
    "invalid api key",
    "api key",
    "token expired",
    "login required",
]

_NETWORK_PATTERNS = [
    "network",
    "connection refused",
    "connection reset",
    "connection timed out",
    "could not resolve",
    "dns",
    "socket",
    "econnrefused",
    "enotfound",
    "no internet",
    "offline",
]

_RATE_LIMIT_PATTERNS = [
    "rate limit",
    "rate-limit",
    "ratelimit",
    "too many requests",
    "429",
    "quota exceeded",
    "capacity",
]

_PERMISSION_PATTERNS = [
    "permission denied",
    "access denied",
    "eacces",
    "eperm",
    "read-only",
    "cannot write",
]

_CLI_NOT_FOUND_PATTERNS = [
    "command not found",
    "not recognized",
    "no such file or directory",
    "enoent",
    "is not recognized as",
]

_CONFIG_PATTERNS = [
    "invalid config",
    "configuration error",
    "missing config",
    "config file",
    "yaml error",
    "parse error",
]


def classify_error(
    output: str,
    exit_code: int | None = None,
    error_message: str | None = None,
) -> ErrorCategory:
    """
    Classify an error based on output and exit code.

    Args:
        output: Combined stdout/stderr output
        exit_code: Process exit code (if available)
        error_message: Optional explicit error message

    Returns:
        ErrorCategory indicating the type of error
    """
    # Combine all text for pattern matching
    text = (output + " " + (error_message or "")).lower()

    # Check patterns in order of specificity
    if any(p in text for p in _CLI_NOT_FOUND_PATTERNS):
        return ErrorCategory.CLI_NOT_FOUND

    if any(p in text for p in _AUTH_PATTERNS):
        return ErrorCategory.AUTH

    if any(p in text for p in _RATE_LIMIT_PATTERNS):
        return ErrorCategory.RATE_LIMIT

    if any(p in text for p in _NETWORK_PATTERNS):
        return ErrorCategory.NETWORK

    if any(p in text for p in _PERMISSION_PATTERNS):
        return ErrorCategory.PERMISSION

    if any(p in text for p in _CONFIG_PATTERNS):
        return ErrorCategory.CONFIG

    if "max turns" in text or "reached max" in text:
        return ErrorCategory.MAX_TURNS

    if "timeout" in text or "timed out" in text:
        return ErrorCategory.TIMEOUT

    return ErrorCategory.UNKNOWN


def get_suggestions(category: ErrorCategory, backend: str = "claude") -> list[str]:
    """
    Get remediation suggestions for an error category.

    Args:
        category: The classified error category
        backend: The AI backend name (for backend-specific suggestions)

    Returns:
        List of actionable suggestion strings
    """
    suggestions_map: dict[ErrorCategory, list[str]] = {
        ErrorCategory.AUTH: [
            f"Check {backend} CLI authentication: `{backend} auth status`",
            f"Re-authenticate if needed: `{backend} auth login`",
            "Verify your API key or subscription is active",
        ],
        ErrorCategory.NETWORK: [
            "Check your internet connection",
            "Verify firewall/proxy settings allow API access",
            "Try again in a few moments (transient network issue)",
        ],
        ErrorCategory.RATE_LIMIT: [
            "Wait a few minutes before retrying",
            "Check your API usage limits and quotas",
            "Consider upgrading your subscription for higher limits",
        ],
        ErrorCategory.CLI_NOT_FOUND: [
            f"Install the {backend} CLI: see https://docs.anthropic.com/claude-code",
            f"Verify `{backend}` is in your PATH: `which {backend}`",
            "Check your shell configuration (.bashrc, .zshrc)",
        ],
        ErrorCategory.PERMISSION: [
            "Check file and directory permissions",
            "Run `galangal doctor` to verify setup",
            "Ensure the tasks directory is writable",
        ],
        ErrorCategory.CONFIG: [
            "Validate your config: `galangal config validate`",
            "Check .galangal/config.yaml for syntax errors",
            "Run `galangal init` to regenerate default config",
        ],
        ErrorCategory.MAX_TURNS: [
            "The task may be too complex for a single run",
            "Try breaking the task into smaller pieces",
            "Increase max_turns in config if task genuinely needs more iterations",
        ],
        ErrorCategory.TIMEOUT: [
            "Increase timeout in config for long-running tasks",
            "Check if the AI is stuck in a loop",
            "Review the task complexity - consider simplifying",
        ],
        ErrorCategory.UNKNOWN: [
            "Run with debug mode: `galangal --debug <command>`",
            "Check logs in logs/galangal_debug.log for details",
            "Report the issue: https://github.com/Galangal-Media/galangal-orchestrate/issues",
        ],
    }

    return suggestions_map.get(category, suggestions_map[ErrorCategory.UNKNOWN])


def analyze_error(
    output: str,
    exit_code: int | None = None,
    error_message: str | None = None,
    backend: str = "claude",
) -> ErrorContext:
    """
    Analyze an error and return structured context with suggestions.

    Args:
        output: Combined stdout/stderr output
        exit_code: Process exit code (if available)
        error_message: Optional explicit error message
        backend: The AI backend name

    Returns:
        ErrorContext with classification, details, and suggestions
    """
    category = classify_error(output, exit_code, error_message)
    suggestions = get_suggestions(category, backend)

    # Extract last few meaningful lines from output
    last_lines = []
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line and not line.startswith("{"):  # Skip JSON lines
            last_lines.insert(0, line)
            if len(last_lines) >= 10:
                break

    # Build message based on category
    messages = {
        ErrorCategory.AUTH: "Authentication required",
        ErrorCategory.NETWORK: "Network connection failed",
        ErrorCategory.RATE_LIMIT: "Rate limit exceeded",
        ErrorCategory.CLI_NOT_FOUND: f"{backend} CLI not found",
        ErrorCategory.PERMISSION: "Permission denied",
        ErrorCategory.CONFIG: "Configuration error",
        ErrorCategory.MAX_TURNS: "Maximum turns exceeded",
        ErrorCategory.TIMEOUT: "Operation timed out",
        ErrorCategory.UNKNOWN: error_message or "Stage execution failed",
    }

    return ErrorContext(
        category=category,
        message=messages.get(category, "Stage execution failed"),
        details=error_message,
        suggestions=suggestions,
        exit_code=exit_code,
        last_output_lines=last_lines,
    )
