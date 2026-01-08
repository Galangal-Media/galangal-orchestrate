"""Tests for Claude backend StageResult returns."""

import json
from unittest.mock import MagicMock, patch

from galangal.ai.claude import ClaudeBackend
from galangal.results import StageResult, StageResultType


class TestClaudeBackendInvoke:
    """Tests for ClaudeBackend.invoke() StageResult returns."""

    def test_successful_invocation_returns_success_result(self):
        """Test that successful invocation returns StageResult.success."""
        backend = ClaudeBackend()

        result_json = json.dumps({"type": "result", "result": "Stage completed", "num_turns": 5})

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]  # Running, then done
        mock_process.stdout.readline.side_effect = [result_json + "\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process):
            with patch("galangal.ai.claude.select.select", return_value=([mock_process.stdout], [], [])):
                result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is True
        assert result.type == StageResultType.SUCCESS
        assert "Stage completed" in result.message

    def test_failed_invocation_returns_error_result(self):
        """Test that failed invocation returns StageResult.error."""
        backend = ClaudeBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 1]
        mock_process.stdout.readline.side_effect = ["some output\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 1

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process):
            with patch("galangal.ai.claude.select.select", return_value=([mock_process.stdout], [], [])):
                result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.ERROR
        assert "exit 1" in result.message

    def test_timeout_returns_timeout_result(self):
        """Test that timeout returns StageResult.timeout."""
        backend = ClaudeBackend()

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Never finishes
        mock_process.kill = MagicMock()

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process):
            with patch("galangal.ai.claude.select.select", return_value=([], [], [])):
                with patch("galangal.ai.claude.time.time") as mock_time:
                    # Simulate timeout - start at 0, then immediately at timeout
                    mock_time.side_effect = [0, 0, 100, 100]
                    result = backend.invoke("test prompt", timeout=50)

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.TIMEOUT
        assert "50" in result.message

    def test_max_turns_returns_max_turns_result(self):
        """Test that max turns exceeded returns StageResult.max_turns."""
        backend = ClaudeBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.side_effect = ["reached max turns limit\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process):
            with patch("galangal.ai.claude.select.select", return_value=([mock_process.stdout], [], [])):
                result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.MAX_TURNS

    def test_pause_check_callback_returns_paused_result(self):
        """Test that pause_check callback returning True returns StageResult.paused."""
        backend = ClaudeBackend()

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.terminate = MagicMock()
        mock_process.wait = MagicMock()

        # Use a callback that returns True (pause requested)
        pause_check = lambda: True

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process):
            with patch("galangal.ai.claude.select.select", return_value=([], [], [])):
                result = backend.invoke("test prompt", pause_check=pause_check)

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.PAUSED

    def test_pause_check_callback_false_continues(self):
        """Test that pause_check callback returning False allows execution to continue."""
        backend = ClaudeBackend()

        result_json = json.dumps({"type": "result", "result": "Stage completed", "num_turns": 5})

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.side_effect = [result_json + "\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        # Use a callback that returns False (no pause)
        pause_check = lambda: False

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process):
            with patch("galangal.ai.claude.select.select", return_value=([mock_process.stdout], [], [])):
                result = backend.invoke("test prompt", pause_check=pause_check)

        assert isinstance(result, StageResult)
        assert result.success is True
        assert result.type == StageResultType.SUCCESS

    def test_exception_returns_error_result(self):
        """Test that exception returns StageResult.error."""
        backend = ClaudeBackend()

        with patch("galangal.ai.claude.subprocess.Popen", side_effect=Exception("Connection failed")):
            result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.ERROR
        assert "Connection failed" in result.message


class TestClaudeBackendName:
    """Tests for ClaudeBackend.name property."""

    def test_name_is_claude(self):
        """Test that backend name is 'claude'."""
        backend = ClaudeBackend()
        assert backend.name == "claude"
