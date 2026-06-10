"""Tests for the SubprocessRunner no-progress watchdog."""

import os
import time
from unittest.mock import MagicMock

from galangal.ai.subprocess import RunOutcome, SubprocessRunner


def test_kill_group_never_signals_group_for_mock_process(monkeypatch):
    """A MagicMock process must NEVER reach os.killpg/getpgid.

    A MagicMock's .pid coerces to 0 via __index__, so os.getpgid(0) would return
    the CALLER's process group and os.killpg would SIGKILL the whole test session
    (this once took down a WSL shell). _kill_group must fall back to .kill().
    """
    killpg_calls = []
    getpgid_calls = []
    monkeypatch.setattr(os, "killpg", lambda *a, **k: killpg_calls.append(a))
    monkeypatch.setattr(os, "getpgid", lambda p: getpgid_calls.append(p) or 0)

    mock_proc = MagicMock()
    SubprocessRunner._kill_group(mock_proc)

    assert killpg_calls == [], "killpg must not be called for a mock/invalid pid"
    assert getpgid_calls == [], "getpgid must not be called for a mock/invalid pid"
    assert mock_proc.kill.called, "should fall back to a plain process.kill()"


def test_kill_group_uses_group_signal_for_real_pid(monkeypatch):
    """For a genuine positive pid, _kill_group does signal the process group."""
    sent = {}
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)  # group == pid
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: sent.update(pgid=pgid, sig=sig))

    proc = MagicMock()
    proc.pid = 4242
    SubprocessRunner._kill_group(proc)

    assert sent.get("pgid") == 4242


def test_watchdog_aborts_silent_process():
    """A process that emits no output is killed once no_progress_timeout passes."""
    runner = SubprocessRunner(
        command="sleep 10",  # produces no output
        timeout=30,
        no_progress_timeout=1,
        poll_interval_idle=0.1,
    )
    start = time.time()
    result = runner.run()
    elapsed = time.time() - start

    assert result.outcome == RunOutcome.TIMEOUT
    assert result.timeout_seconds == 1
    # Should abort shortly after the 1s no-progress window, well before 10s.
    assert elapsed < 5


def test_watchdog_disabled_lets_output_through():
    """With the watchdog off, a quick command completes normally."""
    runner = SubprocessRunner(
        command="echo hello",
        timeout=30,
        no_progress_timeout=0,
        poll_interval_idle=0.1,
    )
    result = runner.run()
    assert result.outcome == RunOutcome.COMPLETED
    assert "hello" in result.output


def test_watchdog_suppressed_does_not_kill():
    """While watchdog_suppressed() is True, a silent process is not killed."""
    runner = SubprocessRunner(
        command="sleep 2",  # silent, would trip a 1s watchdog
        timeout=30,
        no_progress_timeout=1,
        watchdog_suppressed=lambda: True,  # e.g. a rate-limit wait
        poll_interval_idle=0.1,
    )
    result = runner.run()
    # Not killed by the watchdog: it runs to natural completion.
    assert result.outcome == RunOutcome.COMPLETED


def test_watchdog_not_triggered_by_steady_output():
    """A process emitting output within the window is not killed by the watchdog."""
    runner = SubprocessRunner(
        command="for i in 1 2 3; do echo $i; sleep 0.3; done",
        timeout=30,
        no_progress_timeout=2,
        poll_interval_idle=0.1,
    )
    result = runner.run()
    assert result.outcome == RunOutcome.COMPLETED
    assert "3" in result.output
