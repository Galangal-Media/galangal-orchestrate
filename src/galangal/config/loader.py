"""
Configuration loading and management.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from galangal.config.schema import GalangalConfig
from galangal.exceptions import ConfigError

# Global config cache
_config: GalangalConfig | None = None
_project_root: Path | None = None


def find_project_root(start_path: Path | None = None) -> Path:
    """
    Find the project root by looking for .galangal/ directory.
    Falls back to git root, then current directory.
    """
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()

    # Walk up looking for .galangal/
    while current != current.parent:
        if (current / ".galangal").is_dir():
            return current
        if (current / ".git").is_dir():
            # Found git root, use this as fallback
            return current
        current = current.parent

    # Fall back to start path
    return start_path.resolve()


def get_project_root() -> Path:
    """Get the cached project root."""
    global _project_root
    if _project_root is None:
        _project_root = find_project_root()
    return _project_root


def set_project_root(path: Path) -> None:
    """Set the project root (for testing)."""
    global _project_root, _config
    _project_root = path.resolve()
    _config = None  # Reset config cache


def load_config(project_root: Path | None = None) -> GalangalConfig:
    """
    Load configuration from .galangal/config.yaml.

    Returns default config if file doesn't exist.
    Raises ConfigError if file exists but is invalid.
    """
    global _config, _project_root

    if project_root is not None:
        _project_root = project_root.resolve()
    elif _project_root is None:
        _project_root = find_project_root()

    config_path = _project_root / ".galangal" / "config.yaml"

    if not config_path.exists():
        _config = GalangalConfig()
        return _config

    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    try:
        _config = GalangalConfig.model_validate(data)
        return _config
    except PydanticValidationError as e:
        raise ConfigError(f"Invalid configuration in {config_path}: {e}") from e


def get_config() -> GalangalConfig:
    """Get the cached configuration, loading if necessary."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_tasks_dir() -> Path:
    """Get the tasks directory path."""
    config = get_config()
    return get_project_root() / config.tasks_dir


def get_done_dir() -> Path:
    """Get the done tasks directory path."""
    return get_tasks_dir() / "done"


def get_active_file() -> Path:
    """Get the active task marker file path."""
    return get_tasks_dir() / ".active"


def get_prompts_dir() -> Path:
    """Get the project prompts override directory."""
    return get_project_root() / ".galangal" / "prompts"
