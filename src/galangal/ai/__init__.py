"""AI backend abstractions and factory functions."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from galangal.ai.base import AIBackend
from galangal.ai.claude import ClaudeBackend
from galangal.ai.codex import CodexBackend

if TYPE_CHECKING:
    from galangal.config.schema import GalangalConfig
    from galangal.core.state import Stage

# Registry of available backends
BACKEND_REGISTRY: dict[str, type[AIBackend]] = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
}

# Default fallback chain: backend -> fallback
DEFAULT_FALLBACKS: dict[str, str] = {
    "codex": "claude",
    "gemini": "claude",
}


def get_backend(name: str) -> AIBackend:
    """
    Factory function to instantiate backends by name.

    Args:
        name: Backend name (e.g., "claude", "codex")

    Returns:
        Instantiated backend

    Raises:
        ValueError: If backend name is unknown
    """
    backend_class = BACKEND_REGISTRY.get(name.lower())
    if not backend_class:
        available = list(BACKEND_REGISTRY.keys())
        raise ValueError(f"Unknown backend: {name}. Available: {available}")
    return backend_class()


def is_backend_available(name: str) -> bool:
    """
    Check if a backend's CLI tool is available on the system.

    Args:
        name: Backend name (e.g., "claude", "codex")

    Returns:
        True if the backend's CLI is installed and accessible
    """
    cli_commands = {
        "claude": "claude",
        "codex": "codex",
        "gemini": "gemini",  # Future
    }
    cmd = cli_commands.get(name.lower())
    if not cmd:
        return False
    return shutil.which(cmd) is not None


def get_backend_with_fallback(name: str, fallbacks: dict[str, str] | None = None) -> AIBackend:
    """
    Get a backend, falling back to alternatives if unavailable.

    Args:
        name: Primary backend name
        fallbacks: Optional custom fallback mapping. Defaults to DEFAULT_FALLBACKS.

    Returns:
        The requested backend if available, otherwise the fallback backend

    Raises:
        ValueError: If neither primary nor fallback backends are available
    """
    fallbacks = fallbacks or DEFAULT_FALLBACKS

    if is_backend_available(name):
        return get_backend(name)

    # Try fallback
    fallback_name = fallbacks.get(name.lower())
    if fallback_name and is_backend_available(fallback_name):
        return get_backend(fallback_name)

    # Last resort: try claude if it exists
    if name.lower() != "claude" and is_backend_available("claude"):
        return get_backend("claude")

    raise ValueError(f"Backend '{name}' not available and no fallback found")


def get_backend_for_stage(
    stage: Stage,
    config: GalangalConfig,
    use_fallback: bool = True,
) -> AIBackend:
    """
    Get the appropriate backend for a specific stage.

    Checks config.ai.stage_backends for stage-specific overrides,
    otherwise uses config.ai.default.

    Args:
        stage: The workflow stage
        config: Project configuration
        use_fallback: If True, fall back to alternative backends if primary unavailable

    Returns:
        The configured backend for the stage
    """
    # Check for stage-specific backend override
    stage_key = stage.value.upper()
    if stage_key in config.ai.stage_backends:
        backend_name = config.ai.stage_backends[stage_key]
    else:
        backend_name = config.ai.default

    if use_fallback:
        return get_backend_with_fallback(backend_name)
    return get_backend(backend_name)


__all__ = [
    "AIBackend",
    "ClaudeBackend",
    "CodexBackend",
    "BACKEND_REGISTRY",
    "get_backend",
    "get_backend_for_stage",
    "get_backend_with_fallback",
    "is_backend_available",
]
