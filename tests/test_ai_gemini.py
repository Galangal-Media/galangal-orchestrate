"""Tests for Gemini backend."""

from unittest.mock import MagicMock, patch

from galangal.ai.gemini import GeminiBackend
from galangal.results import StageResult, StageResultType

# Patch locations - subprocess logic moved to galangal.ai.subprocess module
SUBPROCESS_POPEN = "galangal.ai.subprocess.subprocess.Popen"
SUBPROCESS_SELECT = "galangal.ai.subprocess.select.select"
SUBPROCESS_TIME = "galangal.ai.subprocess.time.time"


class TestGeminiBackendCommand:
    """Tests for Gemini command construction."""

    def test_default_command_uses_headless_editable_flags(self):
        """Default args should force non-interactive editable mode."""
        backend = GeminiBackend()
        command = backend._build_command("/tmp/prompt.txt", max_turns=200)

        assert "--approval-mode yolo" in command
        assert "--prompt ''" in command
        assert "--output-format stream-json" in command
        assert "--max-tokens" not in command


class TestGeminiBackendInvoke:
    """Tests for GeminiBackend.invoke()."""

    def test_successful_invocation_returns_success_result(self):
        """Exit code 0 returns StageResult.success."""
        backend = GeminiBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.communicate.return_value = ('{"type":"result","text":"done"}\n', "")
        mock_process.returncode = 0

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is True
        assert result.type == StageResultType.SUCCESS
        assert "done" in result.message

    def test_failed_invocation_returns_error_result(self):
        """Non-zero exit returns StageResult.error."""
        backend = GeminiBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 1]
        mock_process.communicate.return_value = ("", "some error")
        mock_process.returncode = 1

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.ERROR

    def test_timeout_returns_timeout_result(self):
        """Timeout should return StageResult.timeout."""
        backend = GeminiBackend()

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Never finishes
        mock_process.kill = MagicMock()

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch(SUBPROCESS_TIME) as mock_time:
                    mock_time.side_effect = [0, 0, 100, 100]
                    result = backend.invoke("test prompt", timeout=50)

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.TIMEOUT

    def test_pause_check_returns_paused_result(self):
        """Pause callback should return StageResult.paused."""
        backend = GeminiBackend()

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.wait = MagicMock()

        def pause_check():
            return True

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                result = backend.invoke("test prompt", pause_check=pause_check)

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.PAUSED


class TestGeminiGenerateText:
    """Tests for GeminiBackend.generate_text()."""

    def test_generate_text_uses_headless_prompt_flag(self):
        """generate_text should run in non-interactive mode."""
        backend = GeminiBackend()

        with patch.object(
            GeminiBackend, "_run_shell_capture", return_value=(0, "hello")
        ) as mock_run:
            text = backend.generate_text("prompt")

        assert text == "hello"
        shell_cmd = mock_run.call_args[0][0]
        assert "--prompt ''" in shell_cmd
        assert "--output-format text" in shell_cmd
