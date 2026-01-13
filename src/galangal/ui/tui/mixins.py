"""
Mixin classes for WorkflowTUIApp functionality.

These mixins separate concerns while keeping the app class cohesive:
- WidgetAccessMixin: Safe widget access patterns
- WorkflowControlMixin: Workflow control state and actions
- PromptsMixin: Modal prompts and text input
- DiscoveryMixin: Discovery Q&A session handling
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from textual.widgets import RichLog

if TYPE_CHECKING:
    from textual.widget import Widget

T = TypeVar("T", bound="Widget")


class WidgetAccessMixin:
    """
    Safe widget access patterns for TUI apps.

    Provides helper methods that gracefully handle widget access
    during screen transitions and shutdown.
    """

    def _safe_query(self, selector: str, widget_type: type[T]) -> T | None:
        """
        Safely query a widget, returning None if not found.

        Use this instead of query_one() when the widget might not exist
        (e.g., during screen transitions or shutdown).

        Args:
            selector: CSS selector for the widget.
            widget_type: Expected widget type.

        Returns:
            The widget if found, None otherwise.
        """
        try:
            return self.query_one(selector, widget_type)
        except Exception:
            return None

    def _safe_update(self, fn: Callable[[], None]) -> None:
        """
        Safely execute a UI update function.

        Tries call_from_thread first (for background thread calls),
        then falls back to direct call. Silently ignores errors
        that occur during screen transitions.

        Args:
            fn: Function to execute for UI update.
        """
        try:
            self.call_from_thread(fn)
        except Exception:
            try:
                fn()
            except Exception:
                pass  # Silently ignore errors during transitions

    def _safe_log_write(self, message: str) -> None:
        """
        Safely write to the activity log.

        Args:
            message: Rich-formatted message to write.
        """
        def _write():
            log = self._safe_query("#activity-log", RichLog)
            if log:
                log.write(message)

        self._safe_update(_write)


class WorkflowControlMixin:
    """
    Workflow control state and related actions.

    Manages the control flags that coordinate between the TUI
    and the background workflow thread.
    """

    def _init_control_state(self) -> None:
        """Initialize workflow control state flags."""
        self._paused = False
        self._interrupt_requested = False
        self._skip_stage_requested = False
        self._back_stage_requested = False
        self._manual_edit_requested = False
        self._workflow_result: str | None = None

    def _reset_control_flags(self) -> None:
        """Reset all control flags to default state."""
        self._paused = False
        self._interrupt_requested = False
        self._skip_stage_requested = False
        self._back_stage_requested = False
        self._manual_edit_requested = False

    @property
    def is_paused(self) -> bool:
        """Check if workflow is paused."""
        return self._paused

    @property
    def has_pending_action(self) -> bool:
        """Check if any control action is pending."""
        return (
            self._interrupt_requested
            or self._skip_stage_requested
            or self._back_stage_requested
            or self._manual_edit_requested
        )


class PromptsMixin:
    """
    Modal prompts and text input handling.

    Provides both callback-based and async versions of prompt methods.
    """

    def _init_prompt_state(self) -> None:
        """Initialize prompt-related state."""
        from galangal.ui.tui.adapters import PromptType

        self._prompt_type = PromptType.NONE
        self._prompt_callback: Callable | None = None
        self._active_prompt_screen = None
        self._input_callback: Callable | None = None
        self._active_input_screen = None

    def _text_input_active(self) -> bool:
        """Check if text input is currently active and should capture keys."""
        return self._input_callback is not None or self._active_input_screen is not None

    def _prompt_active(self) -> bool:
        """Check if a prompt modal is currently active."""
        return self._prompt_callback is not None or self._active_prompt_screen is not None


class DiscoveryMixin:
    """
    Discovery Q&A session handling.

    Provides async methods for the PM stage discovery Q&A flow.
    """

    async def _run_qa_session(self, questions: list[str]) -> list[str] | None:
        """
        Run a Q&A session and return answers.

        This is a convenience wrapper around question_answer_session_async
        that handles the modal display and result collection.

        Args:
            questions: List of questions to ask.

        Returns:
            List of answers, or None if cancelled.
        """
        future: asyncio.Future[list[str] | None] = asyncio.Future()

        def _show():
            from galangal.ui.tui.modals import QuestionAnswerModal

            try:
                def _handle(result: list[str] | None) -> None:
                    if not future.done():
                        future.set_result(result)

                screen = QuestionAnswerModal(questions)
                self.push_screen(screen, _handle)
            except Exception:
                if not future.done():
                    future.set_result(None)

        try:
            self.call_from_thread(_show)
        except Exception:
            _show()

        return await future
