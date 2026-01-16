"""Tests for Claude backend StageResult returns."""

import json
from unittest.mock import MagicMock, patch

from galangal.ai.claude import ClaudeBackend
from galangal.results import StageResult, StageResultType

# Patch locations - subprocess logic moved to galangal.ai.subprocess module
SUBPROCESS_POPEN = "galangal.ai.subprocess.subprocess.Popen"
SUBPROCESS_SELECT = "galangal.ai.subprocess.select.select"
SUBPROCESS_TIME = "galangal.ai.subprocess.time.time"


def make_select_side_effect(mock_stdout, ready_count):
    """Create a select.select side_effect that returns ready N times then not-ready."""
    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= ready_count:
            return ([mock_stdout], [], [])
        return ([], [], [])

    return side_effect


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

        # select returns ready twice (for JSON line + empty), then not-ready
        select_effect = make_select_side_effect(mock_process.stdout, 2)

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, side_effect=select_effect):
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

        select_effect = make_select_side_effect(mock_process.stdout, 2)

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, side_effect=select_effect):
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

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch(SUBPROCESS_TIME) as mock_time:
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

        select_effect = make_select_side_effect(mock_process.stdout, 2)

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, side_effect=select_effect):
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
        def pause_check() -> bool:
            return True

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
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
        def pause_check() -> bool:
            return False

        select_effect = make_select_side_effect(mock_process.stdout, 2)

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, side_effect=select_effect):
                result = backend.invoke("test prompt", pause_check=pause_check)

        assert isinstance(result, StageResult)
        assert result.success is True
        assert result.type == StageResultType.SUCCESS

    def test_exception_returns_error_result(self):
        """Test that exception returns StageResult.error."""
        backend = ClaudeBackend()

        with patch(SUBPROCESS_POPEN, side_effect=Exception("Connection failed")):
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


class TestClaudeBackendTempFilePrompt:
    """Tests for passing prompts via temp file to avoid argument list too long errors."""

    def test_invoke_uses_temp_file_for_prompt(self):
        """Test that invoke() uses a temp file and pipes to claude."""
        backend = ClaudeBackend()

        result_json = json.dumps({"type": "result", "result": "Done", "num_turns": 1})

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.side_effect = [result_json + "\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        select_effect = make_select_side_effect(mock_process.stdout, 2)

        with patch(SUBPROCESS_POPEN, return_value=mock_process) as mock_popen:
            with patch(SUBPROCESS_SELECT, side_effect=select_effect):
                backend.invoke("my test prompt")

        # Verify shell=True is used (for piping)
        call_args = mock_popen.call_args
        assert call_args[1].get("shell") is True

        # Verify the command uses cat | claude pattern
        cmd = call_args[0][0]
        assert "cat " in cmd
        assert "| claude" in cmd
        assert "my test prompt" not in cmd  # prompt NOT in command line

    def test_invoke_handles_large_prompt(self):
        """Test that invoke() can handle prompts exceeding 128KB (Linux arg limit)."""
        backend = ClaudeBackend()

        # Create a prompt larger than 128KB (the typical Linux ARG_MAX limit)
        large_prompt = "x" * 150_000  # ~150KB

        result_json = json.dumps({"type": "result", "result": "Done", "num_turns": 1})

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.side_effect = [result_json + "\n", ""]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        select_effect = make_select_side_effect(mock_process.stdout, 2)

        with patch(SUBPROCESS_POPEN, return_value=mock_process) as mock_popen:
            with patch(SUBPROCESS_SELECT, side_effect=select_effect):
                result = backend.invoke(large_prompt)

        # Verify the large prompt is NOT in the command line
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert large_prompt not in cmd
        assert result.success is True

    def test_generate_text_uses_temp_file(self):
        """Test that generate_text() uses temp file and pipes to claude."""
        backend = ClaudeBackend()

        with patch("galangal.ai.claude.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Generated text")
            backend.generate_text("my prompt")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "cat " in cmd
        assert "| claude" in cmd
        assert "my prompt" not in cmd
        assert call_args[1].get("shell") is True

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
        assert result == "Generated text"


class TestClaudeBackendStderrHandling:
    """Tests for stderr handling to prevent deadlock."""

    def test_stderr_merged_into_stdout(self):
        """Test that Popen is called with stderr=STDOUT to prevent deadlock."""
        import subprocess

        from galangal.ai.claude import ClaudeBackend

        backend = ClaudeBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.readline.return_value = ""
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch(SUBPROCESS_POPEN, return_value=mock_process) as mock_popen:
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                backend.invoke("test prompt", timeout=1)

        # Verify stderr=STDOUT was passed to prevent deadlock
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("stderr") == subprocess.STDOUT
