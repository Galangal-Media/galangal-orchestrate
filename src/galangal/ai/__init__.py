"""AI backend abstractions and factory functions."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from galangal.ai.base import AIBackend
from galangal.ai.claude import ClaudeBackend
from galangal.ai.codex import CodexBackend
from galangal.ai.gemini import GeminiBackend
from galangal.exceptions import AIError, ExitCode

if TYPE_CHECKING:
    from galangal.config.schema import AIBackendConfig, GalangalConfig
    from galangal.core.state import Stage

# Registry of available backends
BACKEND_REGISTRY: dict[str, type[AIBackend]] = {
    "claude": ClaudeBackend,
    "codex": CodexBackend,
    "gemini": GeminiBackend,
}

# Default fallback chain: backend -> fallback
DEFAULT_FALLBACKS: dict[str, str] = {
    "codex": "claude",
    "gemini": "claude",
}


def get_backend(
    name: str,
    config: GalangalConfig | None = None,
) -> AIBackend:
    """
    Factory function to instantiate backends by name.

    Args:
        name: Backend name (e.g., "claude", "codex")
        config: Optional project config to get backend-specific settings

    Returns:
        Instantiated backend with configuration

    Raises:
        AIError: If backend name is unknown
    """
    backend_class = BACKEND_REGISTRY.get(name.lower())
    if not backend_class:
        available = list(BACKEND_REGISTRY.keys())
        raise AIError(f"Unknown backend: {name}. Available: {available}")

    # Get backend-specific config if available
    backend_config: AIBackendConfig | None = None
    if config:
        backend_config = config.ai.backends.get(name.lower())

    return backend_class(backend_config)


def is_backend_available(
    name: str,
    config: GalangalConfig | None = None,
) -> bool:
    """
    Check if a backend's CLI tool is available on the system.

    Args:
        name: Backend name (e.g., "claude", "codex")
        config: Optional project config to get custom command names

    Returns:
        True if the backend's CLI is installed and accessible
    """
    # Check config for custom command name
    cmd: str | None
    if config and name.lower() in config.ai.backends:
        cmd = config.ai.backends[name.lower()].command
    else:
        # Fallback to default command names
        cli_commands = {
            "claude": "claude",
            "codex": "codex",
            "gemini": "gemini",  # Future
        }
        cmd = cli_commands.get(name.lower())

    if not cmd:
        return False
    return shutil.which(cmd) is not None


def get_backend_with_fallback(
    name: str,
    fallbacks: dict[str, str] | None = None,
    config: GalangalConfig | None = None,
) -> AIBackend:
    """
    Get a backend, falling back to alternatives if unavailable.

    Args:
        name: Primary backend name
        fallbacks: Optional custom fallback mapping. Defaults to DEFAULT_FALLBACKS.
        config: Optional project config for backend settings

    Returns:
        The requested backend if available, otherwise the fallback backend

    Raises:
        ValueError: If neither primary nor fallback backends are available
    """
    fallbacks = fallbacks or DEFAULT_FALLBACKS

    if is_backend_available(name, config):
        return get_backend(name, config)

    # Try fallback
    fallback_name = fallbacks.get(name.lower())
    if fallback_name and is_backend_available(fallback_name, config):
        return get_backend(fallback_name, config)

    # Last resort: try claude if it exists
    if name.lower() != "claude" and is_backend_available("claude", config):
        return get_backend("claude", config)

    raise AIError(
        f"Backend '{name}' not available and no fallback found",
        exit_code=ExitCode.AI_NOT_FOUND,
    )


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
        return get_backend_with_fallback(backend_name, config=config)
    return get_backend(backend_name, config)


__all__ = [
    "AIBackend",
    "ClaudeBackend",
    "CodexBackend",
    "GeminiBackend",
    "BACKEND_REGISTRY",
    "get_backend",
    "get_backend_for_stage",
    "get_backend_with_fallback",
    "is_backend_available",
]
