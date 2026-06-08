"""Tests for peer review in headless mode (auto-accept loop, no interactive user)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from galangal.config.schema import GalangalConfig, PeerReviewConfig
from galangal.core.state import Stage
from galangal.core.workflow.engine import EventType, WorkflowEngine, event
from galangal.core.workflow.headless_runner import (
    HeadlessApp,
    _handle_peer_review_headless,
)


def _cfg(auto_accept=True, max_auto_loops=3):
    return GalangalConfig(
        peer_review=PeerReviewConfig(
            enabled=True, auto_accept=auto_accept, max_auto_loops=max_auto_loops
        )
    )


def _engine(decision, notes=""):
    eng = MagicMock(spec=WorkflowEngine)
    eng.state = MagicMock()
    eng.state.stage = Stage.PM
    # Advancing returns a STAGE_STARTED event (so _handle_advance_headless continues).
    eng.handle_action.return_value = event(EventType.STAGE_STARTED, stage=Stage.DESIGN)
    return eng


@pytest.mark.asyncio
async def test_approve_advances(monkeypatch):
    eng = _engine("APPROVE")
    loops = {"PM": 2}
    with (
        patch("galangal.core.workflow.headless_runner.asyncio.to_thread",
              AsyncMock(return_value=("APPROVE", ""))),
        patch("galangal.hub.hooks.notify_output"),
    ):
        result = await _handle_peer_review_headless(HeadlessApp(), eng, _cfg(), loops)
    assert result == "continue"
    eng.accept_peer_review_feedback.assert_not_called()
    eng.handle_action.assert_called_once()  # advanced
    assert "PM" not in loops  # counter reset on approval


@pytest.mark.asyncio
async def test_request_changes_auto_accepts_and_reruns():
    eng = _engine("REQUEST_CHANGES", "fix the spec")
    loops: dict[str, int] = {}
    with (
        patch("galangal.core.workflow.headless_runner.asyncio.to_thread",
              AsyncMock(return_value=("REQUEST_CHANGES", "fix the spec"))),
        patch("galangal.hub.hooks.notify_output"),
    ):
        result = await _handle_peer_review_headless(HeadlessApp(), eng, _cfg(), loops)
    assert result == "continue"  # re-run the same stage
    eng.accept_peer_review_feedback.assert_called_once_with("fix the spec")
    eng.handle_action.assert_not_called()  # did NOT advance
    assert loops["PM"] == 1


@pytest.mark.asyncio
async def test_proceeds_after_max_loops():
    eng = _engine("REQUEST_CHANGES", "still wrong")
    loops = {"PM": 3}  # already at max_auto_loops=3
    with (
        patch("galangal.core.workflow.headless_runner.asyncio.to_thread",
              AsyncMock(return_value=("REQUEST_CHANGES", "still wrong"))),
        patch("galangal.hub.hooks.notify_output"),
    ):
        result = await _handle_peer_review_headless(HeadlessApp(), eng, _cfg(max_auto_loops=3), loops)
    assert result == "continue"
    eng.accept_peer_review_feedback.assert_not_called()  # cap reached -> don't loop
    eng.handle_action.assert_called_once()  # proceed as-is
    assert "PM" not in loops


@pytest.mark.asyncio
async def test_auto_accept_disabled_proceeds_immediately():
    eng = _engine("REQUEST_CHANGES", "x")
    loops: dict[str, int] = {}
    with (
        patch("galangal.core.workflow.headless_runner.asyncio.to_thread",
              AsyncMock(return_value=("REQUEST_CHANGES", "x"))),
        patch("galangal.hub.hooks.notify_output"),
    ):
        result = await _handle_peer_review_headless(
            HeadlessApp(), eng, _cfg(auto_accept=False), loops
        )
    assert result == "continue"
    eng.accept_peer_review_feedback.assert_not_called()
    eng.handle_action.assert_called_once()  # no user to ask -> proceed
