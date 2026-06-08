"""Tests for the doctor active-backend check and non-interactive init --quick."""

from unittest.mock import patch

from galangal.commands.doctor import check_active_backend_cli
from galangal.config.schema import AIBackendConfig, AIConfig, GalangalConfig


def _config(default="claude", backends=None, stage_backends=None):
    return GalangalConfig(
        ai=AIConfig(
            default=default,
            backends=backends or {"claude": AIBackendConfig(command="claude", args=[])},
            stage_backends=stage_backends or {},
        )
    )


class TestActiveBackendCli:
    def test_reports_missing_backend(self):
        cfg = _config(
            default="gemini",
            backends={"gemini": AIBackendConfig(command="gemini-cli-xyz", args=[])},
        )
        with (
            patch("galangal.commands.doctor.is_initialized", return_value=True),
            patch("galangal.config.loader.load_config", return_value=cfg),
            patch("galangal.config.loader.reset_caches"),
            patch("galangal.commands.doctor.shutil.which", return_value=None),
        ):
            ok, detail = check_active_backend_cli()
        assert ok is False
        assert "MISSING" in detail and "gemini" in detail

    def test_reports_found_backend(self):
        cfg = _config()
        with (
            patch("galangal.commands.doctor.is_initialized", return_value=True),
            patch("galangal.config.loader.load_config", return_value=cfg),
            patch("galangal.config.loader.reset_caches"),
            patch("galangal.commands.doctor.shutil.which", return_value="/usr/bin/claude"),
        ):
            ok, detail = check_active_backend_cli()
        assert ok is True
        assert "found" in detail

    def test_includes_per_stage_backends(self):
        cfg = _config(
            stage_backends={"REVIEW": "codex"},
            backends={
                "claude": AIBackendConfig(command="claude", args=[]),
                "codex": AIBackendConfig(command="codex", args=[]),
            },
        )
        seen = {}

        def fake_which(cmd):
            seen[cmd] = True
            return "/x" if cmd == "claude" else None

        with (
            patch("galangal.commands.doctor.is_initialized", return_value=True),
            patch("galangal.config.loader.load_config", return_value=cfg),
            patch("galangal.config.loader.reset_caches"),
            patch("galangal.commands.doctor.shutil.which", side_effect=fake_which),
        ):
            ok, detail = check_active_backend_cli()
        assert "codex" in seen and "claude" in seen  # both checked
        assert ok is False  # codex missing


class TestQuickInitNonInteractive:
    def test_quick_init_no_prompt_when_not_a_tty(self, tmp_path):
        from galangal.commands.init import _run_quick_init

        proj = tmp_path / "myproj"
        (proj / ".galangal").mkdir(parents=True)
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("galangal.commands.init.Prompt.ask") as mock_ask,
            patch("galangal.commands.init._update_gitignore"),
            patch("galangal.commands.init._show_next_steps"),
        ):
            rc = _run_quick_init(proj, proj / ".galangal")

        assert rc == 0
        mock_ask.assert_not_called()  # never prompts without a TTY
        cfg = (proj / ".galangal" / "config.yaml").read_text()
        assert "myproj" in cfg  # defaulted to the directory name
