"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest

from galangal.config import ConfigError
from galangal.config.loader import load_config, set_project_root
from galangal.config.schema import GalangalConfig


def test_default_config():
    """Test that default config loads without errors."""
    config = GalangalConfig()
    assert config.tasks_dir == "galangal-tasks"
    assert config.branch_pattern == "task/{task_name}"
    assert config.stages.timeout == 14400
    assert config.stages.max_retries == 5


def test_config_from_yaml():
    """Test loading config from YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        galangal_dir = project_root / ".galangal"
        galangal_dir.mkdir()

        config_yaml = """
project:
  name: "Test Project"

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


# ── AI Profile Tests ──────────────────────────────────────────────────


class TestAIProfiles:
    """Tests for AI profile resolution."""

    def test_profile_overrides_default_and_stage_backends(self):
        """Active profile replaces top-level default and stage_backends."""
        config = GalangalConfig.model_validate(
            {
                "ai": {
                    "profile": "no-claude",
                    "profiles": {
                        "no-claude": {
                            "default": "gemini",
                            "stage_backends": {"QA": "codex", "REVIEW": "codex"},
                        }
                    },
                }
            }
        )
        assert config.ai.default == "gemini"
        assert config.ai.stage_backends == {"QA": "codex", "REVIEW": "codex"}

    def test_profile_with_peer_review_backend(self):
        """Active profile's peer_review_backend overrides peer_review.backend."""
        config = GalangalConfig.model_validate(
            {
                "ai": {
                    "profile": "alt",
                    "profiles": {
                        "alt": {
                            "default": "gemini",
                            "peer_review_backend": "codex",
                        }
                    },
                },
                "peer_review": {"enabled": True, "backend": "claude"},
            }
        )
        assert config.peer_review.backend == "codex"

    def test_missing_profile_raises_error(self):
        """Referencing a non-existent profile raises a validation error."""
        with pytest.raises(Exception, match="not found"):
            GalangalConfig.model_validate(
                {
                    "ai": {
                        "profile": "ghost",
                        "profiles": {},
                    }
                }
            )

    def test_no_profile_is_backwards_compatible(self):
        """No profile set = no change to default or stage_backends."""
        config = GalangalConfig.model_validate(
            {
                "ai": {
                    "default": "claude",
                    "stage_backends": {"REVIEW": "codex"},
                    "profiles": {
                        "alt": {"default": "gemini"},
                    },
                }
            }
        )
        assert config.ai.default == "claude"
        assert config.ai.stage_backends == {"REVIEW": "codex"}

    def test_profile_without_peer_review_backend_preserves_existing(self):
        """Profile without peer_review_backend doesn't touch peer_review.backend."""
        config = GalangalConfig.model_validate(
            {
                "ai": {
                    "profile": "basic",
                    "profiles": {
                        "basic": {
                            "default": "gemini",
                        }
                    },
                },
                "peer_review": {"backend": "codex"},
            }
        )
        assert config.peer_review.backend == "codex"

    def test_profile_from_yaml_file(self):
        """Profiles load correctly from YAML config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            galangal_dir = project_root / ".galangal"
            galangal_dir.mkdir()

            config_yaml = """
ai:
  profile: prod
  profiles:
    prod:
      default: claude
      stage_backends:
        QA: codex
    fallback:
      default: gemini
      stage_backends:
        QA: codex
        REVIEW: codex
      peer_review_backend: codex
"""
            (galangal_dir / "config.yaml").write_text(config_yaml)

            set_project_root(project_root)
            config = load_config(project_root)

            assert config.ai.profile == "prod"
            assert config.ai.default == "claude"
            assert config.ai.stage_backends == {"QA": "codex"}


class TestProfileCLI:
    """Tests for the profile CLI commands."""

    def test_profile_list_no_profiles(self, capsys):
        """Profile list with no profiles shows info message."""
        import argparse

        from galangal.commands.profile import cmd_profile_list

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            galangal_dir = project_root / ".galangal"
            galangal_dir.mkdir()
            (galangal_dir / "config.yaml").write_text("project:\n  name: Test\n")

            set_project_root(project_root)
            # Force config reload
            load_config(project_root)

            result = cmd_profile_list(argparse.Namespace())
            assert result == 0

    def test_profile_switch_updates_config(self):
        """Profile switch writes the profile name to config.yaml."""
        import argparse

        from galangal.commands.profile import cmd_profile_switch

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            galangal_dir = project_root / ".galangal"
            galangal_dir.mkdir()

            config_yaml = """
ai:
  profiles:
    alt:
      default: gemini
"""
            (galangal_dir / "config.yaml").write_text(config_yaml)

            set_project_root(project_root)
            load_config(project_root)

            result = cmd_profile_switch(argparse.Namespace(name="alt"))
            assert result == 0

            # Verify config file was updated
            import yaml

            data = yaml.safe_load((galangal_dir / "config.yaml").read_text())
            assert data["ai"]["profile"] == "alt"

    def test_profile_switch_nonexistent(self):
        """Profile switch with unknown name returns error."""
        import argparse

        from galangal.commands.profile import cmd_profile_switch

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            galangal_dir = project_root / ".galangal"
            galangal_dir.mkdir()

            config_yaml = """
ai:
  profiles:
    alt:
      default: gemini
"""
            (galangal_dir / "config.yaml").write_text(config_yaml)

            set_project_root(project_root)
            load_config(project_root)

            result = cmd_profile_switch(argparse.Namespace(name="ghost"))
            assert result == 1
