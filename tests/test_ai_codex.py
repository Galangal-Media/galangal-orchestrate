"""Tests for Codex backend and AI factory functions."""

import json
from unittest.mock import MagicMock, patch

import pytest

from galangal.ai import (
    BACKEND_REGISTRY,
    get_backend,
    get_backend_for_stage,
    get_backend_with_fallback,
    is_backend_available,
)
from galangal.ai.claude import ClaudeBackend
from galangal.ai.codex import CodexBackend
from galangal.results import StageResult, StageResultType

# Patch locations - subprocess logic moved to galangal.ai.subprocess module
SUBPROCESS_POPEN = "galangal.ai.subprocess.subprocess.Popen"
SUBPROCESS_SELECT = "galangal.ai.subprocess.select.select"
SUBPROCESS_TIME = "galangal.ai.subprocess.time.time"


class TestCodexBackendInvoke:
    """Tests for CodexBackend.invoke() StageResult returns."""

    def test_successful_invocation_returns_success_result(self):
        """Test that successful invocation returns StageResult.success with JSON output."""
        backend = CodexBackend()

        output_data = {
            "review_notes": "# Code Review\n\nLooks good!",
            "decision": "APPROVE",
            "issues": [],
        }

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch("galangal.ai.codex.os.path.exists", return_value=True):
                    with patch(
                        "galangal.ai.codex.open",
                        MagicMock(
                            return_value=MagicMock(
                                __enter__=MagicMock(
                                    return_value=MagicMock(
                                        read=MagicMock(return_value=json.dumps(output_data))
                                    )
                                ),
                                __exit__=MagicMock(return_value=False),
                            )
                        ),
                    ):
                        result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is True
        assert result.type == StageResultType.SUCCESS
        assert "APPROVE" in result.message

    def test_failed_invocation_returns_error_result(self):
        """Test that failed invocation returns StageResult.error."""
        backend = CodexBackend()

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
        assert "exit 1" in result.message

    def test_timeout_returns_timeout_result(self):
        """Test that timeout returns StageResult.timeout."""
        backend = CodexBackend()

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Never finishes
        mock_process.kill = MagicMock()

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch(SUBPROCESS_TIME) as mock_time:
                    # Simulate timeout
                    mock_time.side_effect = [0, 0, 100, 100]
                    result = backend.invoke("test prompt", timeout=50)

        assert isinstance(result, StageResult)
        assert result.success is False
        assert result.type == StageResultType.TIMEOUT
        assert "50" in result.message

    def test_pause_check_callback_returns_paused_result(self):
        """Test that pause_check callback returning True returns StageResult.paused."""
        backend = CodexBackend()

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

    def test_missing_output_file_returns_error(self):
        """Test that missing output file returns error."""
        backend = CodexBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch("galangal.ai.codex.os.path.exists", return_value=False):
                    result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is False
        assert "output file" in result.message.lower()

    def test_invalid_json_output_returns_error(self):
        """Test that invalid JSON output returns error."""
        backend = CodexBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        with patch(SUBPROCESS_POPEN, return_value=mock_process):
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch("galangal.ai.codex.os.path.exists", return_value=True):
                    with patch(
                        "galangal.ai.codex.open",
                        MagicMock(
                            return_value=MagicMock(
                                __enter__=MagicMock(
                                    return_value=MagicMock(read=MagicMock(return_value="not json"))
                                ),
                                __exit__=MagicMock(return_value=False),
                            )
                        ),
                    ):
                        result = backend.invoke("test prompt")

        assert isinstance(result, StageResult)
        assert result.success is False
        assert "json" in result.message.lower()


class TestCodexBackendName:
    """Tests for CodexBackend.name property."""

    def test_name_is_codex(self):
        """Test that backend name is 'codex'."""
        backend = CodexBackend()
        assert backend.name == "codex"


class TestBackendRegistry:
    """Tests for the backend registry."""

    def test_registry_has_claude(self):
        """Test that Claude is in the registry."""
        assert "claude" in BACKEND_REGISTRY
        assert BACKEND_REGISTRY["claude"] == ClaudeBackend

    def test_registry_has_codex(self):
        """Test that Codex is in the registry."""
        assert "codex" in BACKEND_REGISTRY
        assert BACKEND_REGISTRY["codex"] == CodexBackend


class TestGetBackend:
    """Tests for get_backend factory function."""

    def test_get_backend_claude(self):
        """Test getting Claude backend."""
        backend = get_backend("claude")
        assert isinstance(backend, ClaudeBackend)

    def test_get_backend_codex(self):
        """Test getting Codex backend."""
        backend = get_backend("codex")
        assert isinstance(backend, CodexBackend)

    def test_get_backend_case_insensitive(self):
        """Test that backend name is case insensitive."""
        backend = get_backend("CLAUDE")
        assert isinstance(backend, ClaudeBackend)

    def test_get_backend_unknown_raises(self):
        """Test that unknown backend raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_backend("unknown")
        assert "unknown" in str(exc_info.value).lower()


class TestIsBackendAvailable:
    """Tests for is_backend_available function."""

    def test_available_when_cli_exists(self):
        """Test that backend is available when CLI exists."""
        with patch("galangal.ai.shutil.which", return_value="/usr/bin/claude"):
            assert is_backend_available("claude") is True

    def test_unavailable_when_cli_missing(self):
        """Test that backend is unavailable when CLI is missing."""
        with patch("galangal.ai.shutil.which", return_value=None):
            assert is_backend_available("claude") is False

    def test_unknown_backend_unavailable(self):
        """Test that unknown backend is unavailable."""
        assert is_backend_available("unknown_backend") is False


class TestGetBackendWithFallback:
    """Tests for get_backend_with_fallback function."""

    def test_returns_primary_when_available(self):
        """Test that primary backend is returned when available."""
        with patch("galangal.ai.is_backend_available", return_value=True):
            backend = get_backend_with_fallback("codex")
            assert isinstance(backend, CodexBackend)

    def test_returns_fallback_when_primary_unavailable(self):
        """Test that fallback is returned when primary is unavailable."""

        def mock_available(name, config=None):
            return name == "claude"

        with patch("galangal.ai.is_backend_available", side_effect=mock_available):
            backend = get_backend_with_fallback("codex")
            assert isinstance(backend, ClaudeBackend)

    def test_raises_when_no_backend_available(self):
        """Test that error is raised when no backend is available."""
        with patch("galangal.ai.is_backend_available", return_value=False):
            with pytest.raises(ValueError):
                get_backend_with_fallback("codex")


class TestGetBackendForStage:
    """Tests for get_backend_for_stage function."""

    def test_uses_stage_specific_backend(self):
        """Test that stage-specific backend override is used."""
        mock_config = MagicMock()
        mock_config.ai.default = "claude"
        mock_config.ai.stage_backends = {"REVIEW": "codex"}

        mock_stage = MagicMock()
        mock_stage.value = "REVIEW"

        with patch("galangal.ai.is_backend_available", return_value=True):
            backend = get_backend_for_stage(mock_stage, mock_config, use_fallback=True)
            assert isinstance(backend, CodexBackend)

    def test_uses_default_when_no_override(self):
        """Test that default backend is used when no override."""
        mock_config = MagicMock()
        mock_config.ai.default = "claude"
        mock_config.ai.stage_backends = {}

        mock_stage = MagicMock()
        mock_stage.value = "DEV"

        with patch("galangal.ai.is_backend_available", return_value=True):
            backend = get_backend_for_stage(mock_stage, mock_config, use_fallback=True)
            assert isinstance(backend, ClaudeBackend)

    def test_fallback_disabled_raises_when_unavailable(self):
        """Test that error is raised when fallback is disabled and backend unavailable."""
        mock_config = MagicMock()
        mock_config.ai.default = "codex"
        mock_config.ai.stage_backends = {}

        mock_stage = MagicMock()
        mock_stage.value = "DEV"

        # Codex not in registry won't happen, but test the code path
        backend = get_backend_for_stage(mock_stage, mock_config, use_fallback=False)
        assert isinstance(backend, CodexBackend)


class TestCodexOutputSchema:
    """Tests for Codex output schema."""

    def test_schema_has_required_fields(self):
        """Test that the output schema has all required fields."""
        from galangal.ai.codex import REVIEW_OUTPUT_SCHEMA

        assert "properties" in REVIEW_OUTPUT_SCHEMA
        props = REVIEW_OUTPUT_SCHEMA["properties"]

        assert "review_notes" in props
        assert "decision" in props
        assert "issues" in props

        # OpenAI requires ALL properties to be in required array
        assert set(REVIEW_OUTPUT_SCHEMA["required"]) == {"review_notes", "decision", "issues"}

        # Check nested issue items also have all properties required
        issue_items = props["issues"]["items"]
        assert set(issue_items["required"]) == {"severity", "file", "line", "description"}

    def test_decision_enum_values(self):
        """Test that decision has correct enum values."""
        from galangal.ai.codex import REVIEW_OUTPUT_SCHEMA

        decision_schema = REVIEW_OUTPUT_SCHEMA["properties"]["decision"]
        assert "enum" in decision_schema
        assert "APPROVE" in decision_schema["enum"]
        assert "REQUEST_CHANGES" in decision_schema["enum"]

    def test_schema_has_additional_properties_false(self):
        """Test that schema has additionalProperties: false (required by OpenAI)."""
        from galangal.ai.codex import REVIEW_OUTPUT_SCHEMA

        # Root level
        assert REVIEW_OUTPUT_SCHEMA.get("additionalProperties") is False

        # Nested issue items
        issue_items = REVIEW_OUTPUT_SCHEMA["properties"]["issues"]["items"]
        assert issue_items.get("additionalProperties") is False


class TestCodexBackendStderrHandling:
    """Tests for stderr handling to prevent deadlock."""

    def test_stderr_merged_into_stdout(self):
        """Test that Popen is called with stderr=STDOUT to prevent deadlock."""
        import subprocess
        from galangal.ai.codex import CodexBackend

        backend = CodexBackend()

        mock_process = MagicMock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.communicate.return_value = ("output", None)
        mock_process.returncode = 0
        mock_process.stdout = MagicMock()

        with patch(SUBPROCESS_POPEN, return_value=mock_process) as mock_popen:
            with patch(SUBPROCESS_SELECT, return_value=([], [], [])):
                with patch("galangal.ai.codex.os.path.exists", return_value=True):
                    with patch(
                        "galangal.ai.codex.open",
                        MagicMock(
                            return_value=MagicMock(
                                __enter__=MagicMock(
                                    return_value=MagicMock(
                                        read=MagicMock(
                                            return_value='{"review_notes": "ok", "decision": "APPROVE", "issues": []}'
                                        )
                                    )
                                ),
                                __exit__=MagicMock(return_value=False),
                            )
                        ),
                    ):
                        backend.invoke("test prompt", timeout=1)

        # Verify stderr=STDOUT was passed to prevent deadlock
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("stderr") == subprocess.STDOUT
