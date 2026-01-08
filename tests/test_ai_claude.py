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


class TestClaudeBackendStdinPrompt:
    """Tests for passing prompts via stdin to avoid argument list too long errors."""

    def test_invoke_passes_prompt_via_stdin(self):
        """Test that invoke() uses stdin for the prompt instead of command line args."""
        backend = ClaudeBackend()

        result_json = json.dumps({"type": "result", "result": "Done", "num_turns": 1})

        mock_stdin = MagicMock()
        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.side_effect = [result_json + "\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process) as mock_popen:
            with patch("galangal.ai.claude.select.select", return_value=([mock_process.stdout], [], [])):
                backend.invoke("my test prompt")

        # Verify command uses stdin mode
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "-p" in cmd
        assert "-" in cmd  # stdin marker
        assert "my test prompt" not in cmd  # prompt NOT in command line

        # Verify stdin was used
        assert call_args[1].get("stdin") is not None
        mock_stdin.write.assert_called_once_with("my test prompt")
        mock_stdin.close.assert_called_once()

    def test_invoke_handles_large_prompt(self):
        """Test that invoke() can handle prompts exceeding 128KB (Linux arg limit)."""
        backend = ClaudeBackend()

        # Create a prompt larger than 128KB (the typical Linux ARG_MAX limit)
        large_prompt = "x" * 150_000  # ~150KB

        result_json = json.dumps({"type": "result", "result": "Done", "num_turns": 1})

        mock_stdin = MagicMock()
        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.side_effect = [result_json + "\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch("galangal.ai.claude.subprocess.Popen", return_value=mock_process) as mock_popen:
            with patch("galangal.ai.claude.select.select", return_value=([mock_process.stdout], [], [])):
                result = backend.invoke(large_prompt)

        # Verify the large prompt was written to stdin (not passed as arg)
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert large_prompt not in cmd  # Not in command line
        mock_stdin.write.assert_called_once_with(large_prompt)
        assert result.success is True

    def test_generate_text_passes_prompt_via_stdin(self):
        """Test that generate_text() uses stdin for the prompt."""
        backend = ClaudeBackend()

        with patch("galangal.ai.claude.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Generated text")
            backend.generate_text("my prompt")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "-p" in cmd
        assert "-" in cmd
        assert "my prompt" not in cmd
        assert call_args[1].get("input") == "my prompt"

    def test_generate_text_handles_large_prompt(self):
        """Test that generate_text() can handle prompts exceeding 128KB."""
        backend = ClaudeBackend()

        large_prompt = "y" * 150_000  # ~150KB

        with patch("galangal.ai.claude.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Generated text")
            result = backend.generate_text(large_prompt)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert large_prompt not in cmd
        assert call_args[1].get("input") == large_prompt
        assert result == "Generated text"
