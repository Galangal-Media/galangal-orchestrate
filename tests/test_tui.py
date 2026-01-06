"""
Tests for the TUI components using Textual's pilot framework.
"""

import pytest
from textual.pilot import Pilot
from textual.widgets import Input

from galangal.ui.tui import WorkflowTUIApp, PromptType


@pytest.fixture
def app():
    """Create a test app instance."""
    return WorkflowTUIApp(task_name="test-task", initial_stage="PM", max_retries=5)


class TestTextInput:
    """Tests for text input functionality."""

    @pytest.mark.asyncio
    async def test_text_input_displays(self, app):
        """Test that text input widget is always visible and accepts values."""
        async with app.run_test() as pilot:
            # Input should always be visible
            text_input = app.query_one("#text-input", Input)

            # Show text input with default value
            callback_result = []
            app.show_text_input("Enter name:", "default", lambda v: callback_result.append(v))

            await pilot.pause()

            text_input = app.query_one("#text-input", Input)
            assert text_input.value == "default"
            assert text_input.placeholder == "Enter name:"

    @pytest.mark.asyncio
    async def test_text_input_accepts_typing(self, app):
        """Test that text input accepts keyboard input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_text_input("Enter name:", "", lambda v: callback_result.append(v))

            await pilot.pause()

            # Type some text
            await pilot.press("t", "e", "s", "t")
            await pilot.pause()

            text_input = app.query_one("#text-input", Input)
            assert text_input.value == "test"

    @pytest.mark.asyncio
    async def test_text_input_submit(self, app):
        """Test that Enter key submits text input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_text_input("Enter name:", "", lambda v: callback_result.append(v))

            await pilot.pause()

            # Type and submit
            await pilot.press("h", "e", "l", "l", "o")
            await pilot.press("enter")
            await pilot.pause()

            assert callback_result == ["hello"]

    @pytest.mark.asyncio
    async def test_text_input_escape_cancels(self, app):
        """Test that Escape key cancels text input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_text_input("Enter name:", "", lambda v: callback_result.append(v))

            await pilot.pause()

            # Type then cancel
            await pilot.press("t", "e", "s", "t")
            await pilot.press("escape")
            await pilot.pause()

            # Callback should receive None for cancelled
            assert callback_result == [None]

    @pytest.mark.asyncio
    async def test_bindings_disabled_during_input(self, app):
        """Test that app bindings don't interfere with text input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_text_input("Enter name:", "", lambda v: callback_result.append(v))

            await pilot.pause()

            # Type 'q' - should go into input, not quit
            await pilot.press("q", "u", "i", "t")
            await pilot.pause()

            text_input = app.query_one("#text-input", Input)
            assert text_input.value == "quit"

            # App should still be running
            assert app.is_running


class TestPromptActions:
    """Tests for approval prompt actions."""

    @pytest.mark.asyncio
    async def test_option_1_action_calls_yes(self, app):
        """Test that action_select_option_1 triggers yes callback."""
        async with app.run_test() as pilot:
            callback_result = []
            app._prompt_callback = lambda v: callback_result.append(v)

            # Call action directly
            app.action_select_option_1()
            await pilot.pause()

            assert callback_result == ["yes"]

    @pytest.mark.asyncio
    async def test_option_2_action_calls_no(self, app):
        """Test that action_select_option_2 triggers no callback."""
        async with app.run_test() as pilot:
            callback_result = []
            app._prompt_callback = lambda v: callback_result.append(v)

            app.action_select_option_2()
            await pilot.pause()

            assert callback_result == ["no"]

    @pytest.mark.asyncio
    async def test_option_3_action_calls_quit(self, app):
        """Test that action_select_option_3 triggers quit callback."""
        async with app.run_test() as pilot:
            callback_result = []
            app._prompt_callback = lambda v: callback_result.append(v)

            app.action_select_option_3()
            await pilot.pause()

            assert callback_result == ["quit"]

    @pytest.mark.asyncio
    async def test_check_action_blocks_when_input_active(self, app):
        """Test that check_action returns False when input is active."""
        async with app.run_test() as pilot:
            # When no input active, check_action should return True
            assert app.check_action_select_option_1() is True

            # When input is active, check_action should return False
            app._input_callback = lambda v: None
            assert app.check_action_select_option_1() is False
