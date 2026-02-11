"""Tests for doctor command checks."""

import argparse
from unittest.mock import patch

from galangal.config.schema import GalangalConfig


def _make_config() -> GalangalConfig:
    """Create a config object with default backend settings."""
    return GalangalConfig()


def test_is_legacy_codex_args_detects_schema_markers():
    """Legacy structured-output markers should be detected."""
    from galangal.commands.doctor import _is_legacy_codex_args

    assert _is_legacy_codex_args(["exec", "--full-auto", "--output-schema", "{schema_file}"])
    assert _is_legacy_codex_args(["exec", "-o", "{output_file}"])
    assert _is_legacy_codex_args(["exec", "--full-auto", "foo-{schema_file}.json"])
    assert not _is_legacy_codex_args(["exec", "--full-auto"])


def test_check_codex_backend_mode_not_initialized():
    """Uninitialized projects should return optional warning status."""
    from galangal.commands.doctor import check_codex_backend_mode

    with patch("galangal.commands.doctor.is_initialized", return_value=False):
        result, detail = check_codex_backend_mode()

    assert result is None
    assert "not initialized" in detail.lower()


def test_check_codex_backend_mode_flags_read_only():
    """read_only=true should be flagged as legacy config."""
    from galangal.commands.doctor import check_codex_backend_mode

    cfg = _make_config()
    cfg.ai.backends["codex"].read_only = True

    with (
        patch("galangal.commands.doctor.is_initialized", return_value=True),
        patch("galangal.config.loader.reset_caches"),
        patch("galangal.config.loader.load_config", return_value=cfg),
    ):
        result, detail = check_codex_backend_mode()

    assert result is None
    assert "legacy read-only config" in detail.lower()
    assert "read_only=true" in detail


def test_check_codex_backend_mode_flags_output_schema_args():
    """Structured-output args should be flagged as legacy config."""
    from galangal.commands.doctor import check_codex_backend_mode

    cfg = _make_config()
    cfg.ai.backends["codex"].read_only = False
    cfg.ai.backends["codex"].args = [
        "exec",
        "--full-auto",
        "--output-schema",
        "{schema_file}",
        "-o",
        "{output_file}",
    ]

    with (
        patch("galangal.commands.doctor.is_initialized", return_value=True),
        patch("galangal.config.loader.reset_caches"),
        patch("galangal.config.loader.load_config", return_value=cfg),
    ):
        result, detail = check_codex_backend_mode()

    assert result is None
    assert "legacy read-only config" in detail.lower()
    assert "output-schema args" in detail


def test_check_codex_backend_mode_editable_ok():
    """Editable Codex config should pass."""
    from galangal.commands.doctor import check_codex_backend_mode

    cfg = _make_config()
    cfg.ai.backends["codex"].read_only = False
    cfg.ai.backends["codex"].args = ["exec", "--full-auto"]

    with (
        patch("galangal.commands.doctor.is_initialized", return_value=True),
        patch("galangal.config.loader.reset_caches"),
        patch("galangal.config.loader.load_config", return_value=cfg),
    ):
        result, detail = check_codex_backend_mode()

    assert result is True
    assert "editable mode" in detail.lower()


def test_check_gemini_backend_mode_flags_legacy_args():
    """Legacy Gemini args should be flagged as non-editable."""
    from galangal.commands.doctor import check_gemini_backend_mode

    cfg = _make_config()
    cfg.ai.backends["gemini"].args = [
        "--output-format",
        "stream-json",
        "--max-tokens",
        "8192",
    ]

    with (
        patch("galangal.commands.doctor.is_initialized", return_value=True),
        patch("galangal.config.loader.reset_caches"),
        patch("galangal.config.loader.load_config", return_value=cfg),
    ):
        result, detail = check_gemini_backend_mode()

    assert result is None
    assert "legacy/non-editable config" in detail.lower()
    assert "missing --prompt" in detail


def test_check_gemini_backend_mode_headless_editable_ok():
    """Headless editable Gemini config should pass."""
    from galangal.commands.doctor import check_gemini_backend_mode

    cfg = _make_config()
    cfg.ai.backends["gemini"].args = [
        "--approval-mode",
        "yolo",
        "--prompt",
        "",
        "--output-format",
        "stream-json",
    ]
    cfg.ai.backends["gemini"].read_only = False

    with (
        patch("galangal.commands.doctor.is_initialized", return_value=True),
        patch("galangal.config.loader.reset_caches"),
        patch("galangal.config.loader.load_config", return_value=cfg),
    ):
        result, detail = check_gemini_backend_mode()

    assert result is True
    assert "headless editable mode" in detail.lower()


def test_cmd_doctor_prints_codex_migration_hint():
    """Doctor output includes migration snippet when legacy Codex is detected."""
    from galangal.commands import doctor

    args = argparse.Namespace()

    with (
        patch.object(doctor, "check_python_version", return_value=(True, "3.12.0")),
        patch.object(doctor, "check_git_installed", return_value=(True, "2.47.0")),
        patch.object(doctor, "check_git_config", return_value=(True, "Dev <dev@example.com>")),
        patch.object(doctor, "check_claude_cli", return_value=(True, "1.0.0")),
        patch.object(doctor, "check_github_cli", return_value=(None, "Optional")),
        patch.object(doctor, "check_config_valid", return_value=(True, "Valid")),
        patch.object(
            doctor,
            "check_codex_backend_mode",
            return_value=(None, "Legacy read-only config detected (read_only=true)"),
        ),
        patch.object(doctor, "check_gemini_backend_mode", return_value=(True, "Headless editable")),
        patch.object(doctor, "check_tasks_dir", return_value=(True, "Writable")),
        patch.object(doctor, "check_mistake_tracking", return_value=(None, "Optional")),
        patch.object(doctor.console, "print") as mock_print,
    ):
        result = doctor.cmd_doctor(args)

    assert result == 0
    rendered = "\n".join(call.args[0] for call in mock_print.call_args_list if call.args)
    assert "Codex is in legacy read-only mode." in rendered
    assert "read_only: false" in rendered


def test_cmd_doctor_prints_gemini_migration_hint():
    """Doctor output includes Gemini migration snippet when legacy config is detected."""
    from galangal.commands import doctor

    args = argparse.Namespace()

    with (
        patch.object(doctor, "check_python_version", return_value=(True, "3.12.0")),
        patch.object(doctor, "check_git_installed", return_value=(True, "2.47.0")),
        patch.object(doctor, "check_git_config", return_value=(True, "Dev <dev@example.com>")),
        patch.object(doctor, "check_claude_cli", return_value=(True, "1.0.0")),
        patch.object(doctor, "check_github_cli", return_value=(None, "Optional")),
        patch.object(doctor, "check_config_valid", return_value=(True, "Valid")),
        patch.object(doctor, "check_codex_backend_mode", return_value=(True, "Editable")),
        patch.object(
            doctor,
            "check_gemini_backend_mode",
            return_value=(None, "Legacy/non-editable config detected (missing --prompt/-p)"),
        ),
        patch.object(doctor, "check_tasks_dir", return_value=(True, "Writable")),
        patch.object(doctor, "check_mistake_tracking", return_value=(None, "Optional")),
        patch.object(doctor.console, "print") as mock_print,
    ):
        result = doctor.cmd_doctor(args)

    assert result == 0
    rendered = "\n".join(call.args[0] for call in mock_print.call_args_list if call.args)
    assert "Gemini is in legacy/non-editable mode." in rendered
    assert "--approval-mode\", \"yolo\"" in rendered
