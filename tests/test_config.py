"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest

from galangal.config import ConfigError
from galangal.config.loader import load_config, set_project_root
from galangal.config.schema import GalangalConfig, StackConfig


def test_default_config():
    """Test that default config loads without errors."""
    config = GalangalConfig()
    assert config.tasks_dir == "galangal-tasks"
    assert config.branch_pattern == "task/{task_name}"
    assert config.stages.timeout == 14400
    assert config.stages.max_retries == 5


def test_stack_config():
    """Test stack configuration."""
    stack = StackConfig(language="python", framework="fastapi", root="backend/")
    assert stack.language == "python"
    assert stack.framework == "fastapi"
    assert stack.root == "backend/"


def test_config_from_yaml():
    """Test loading config from YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        galangal_dir = project_root / ".galangal"
        galangal_dir.mkdir()

        config_yaml = """
project:
  name: "Test Project"
  stacks:
    - language: python
      framework: django

stages:
  skip:
    - BENCHMARK
  max_retries: 3

pr:
  codex_review: true
"""
        (galangal_dir / "config.yaml").write_text(config_yaml)

        set_project_root(project_root)
        config = load_config(project_root)

        assert config.project.name == "Test Project"
        assert len(config.project.stacks) == 1
        assert config.project.stacks[0].language == "python"
        assert config.project.stacks[0].framework == "django"
        assert "BENCHMARK" in config.stages.skip
        assert config.stages.max_retries == 3
        assert config.pr.codex_review is True


def test_invalid_yaml_raises_config_error():
    """Test that invalid YAML raises ConfigError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        galangal_dir = project_root / ".galangal"
        galangal_dir.mkdir()

        # Invalid YAML - bad indentation
        invalid_yaml = """
project:
  name: "Test"
    invalid: indentation
"""
        (galangal_dir / "config.yaml").write_text(invalid_yaml)

        set_project_root(project_root)
        with pytest.raises(ConfigError) as exc_info:
            load_config(project_root)

        assert "Invalid YAML" in str(exc_info.value)


def test_invalid_config_values_raises_config_error():
    """Test that invalid config values raise ConfigError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        galangal_dir = project_root / ".galangal"
        galangal_dir.mkdir()

        # Valid YAML but invalid config values
        invalid_config = """
stages:
  max_retries: "not a number"
"""
        (galangal_dir / "config.yaml").write_text(invalid_config)

        set_project_root(project_root)
        with pytest.raises(ConfigError) as exc_info:
            load_config(project_root)

        assert "Invalid configuration" in str(exc_info.value)
