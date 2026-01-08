"""
Tests for the TUI components using Textual's pilot framework.
"""

import pytest

from galangal.ui.tui import PromptType, WorkflowTUIApp


@pytest.fixture
def app():
    """Create a test app instance."""
    return WorkflowTUIApp(task_name="test-task", initial_stage="PM", max_retries=5)


class TestTextInput:
    """Tests for text input modal functionality."""

    @pytest.mark.asyncio
    async def test_text_input_submit(self, app):
        """Test that Enter key submits text input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_text_input("Enter name:", "", lambda v: callback_result.append(v))

            # Wait for modal to appear
            await pilot.pause()
            await pilot.pause()

            # Type and submit - keypresses go to focused input
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


class TestMultilineInput:
    """Tests for multiline text input modal functionality."""

    @pytest.mark.asyncio
    async def test_multiline_input_submit_with_ctrl_s(self, app):
        """Test that Ctrl+S submits multiline text input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_multiline_input("Enter description:", "", lambda v: callback_result.append(v))

            # Wait for modal to appear
            await pilot.pause()
            await pilot.pause()

            # Type some text
            await pilot.press("h", "e", "l", "l", "o")
            await pilot.pause()

            # Submit with Ctrl+S
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert callback_result == ["hello"]

    @pytest.mark.asyncio
    async def test_multiline_input_escape_cancels(self, app):
        """Test that Escape key cancels multiline text input."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_multiline_input("Enter description:", "", lambda v: callback_result.append(v))

            await pilot.pause()

            # Type then cancel
            await pilot.press("t", "e", "s", "t")
            await pilot.press("escape")
            await pilot.pause()

            # Callback should receive None for cancelled
            assert callback_result == [None]

    @pytest.mark.asyncio
    async def test_multiline_input_with_default(self, app):
        """Test multiline input with default value."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_multiline_input("Edit:", "default text", lambda v: callback_result.append(v))

            # Wait for modal to appear
            await pilot.pause()
            await pilot.pause()

            # Submit without changes
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert callback_result == ["default text"]


class TestPromptActions:
    """Tests for approval prompt modal actions."""

    @pytest.mark.asyncio
    async def test_prompt_modal_option_1(self, app):
        """Test that pressing 1 triggers option 1 callback."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_prompt(PromptType.PLAN_APPROVAL, "Test prompt", lambda v: callback_result.append(v))

            await pilot.pause()

            # Press 1 to select first option
            await pilot.press("1")
            await pilot.pause()

            assert callback_result == ["yes"]

    @pytest.mark.asyncio
    async def test_prompt_modal_option_2(self, app):
        """Test that pressing 2 triggers option 2 callback."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_prompt(PromptType.PLAN_APPROVAL, "Test prompt", lambda v: callback_result.append(v))

            await pilot.pause()

            # Press 2 to select second option
            await pilot.press("2")
            await pilot.pause()

            assert callback_result == ["no"]

    @pytest.mark.asyncio
    async def test_prompt_modal_escape_quits(self, app):
        """Test that pressing Escape triggers quit callback."""
        async with app.run_test() as pilot:
            callback_result = []
            app.show_prompt(PromptType.PLAN_APPROVAL, "Test prompt", lambda v: callback_result.append(v))

            await pilot.pause()

            # Press Escape to quit
            await pilot.press("escape")
            await pilot.pause()

            assert callback_result == ["quit"]

    @pytest.mark.asyncio
    async def test_check_action_blocks_when_input_active(self, app):
        """Test that check_action returns False when input is active."""
        async with app.run_test() as _:
            # When no input active, check_action should return True
            assert app.check_action_quit_workflow() is True

            # When input is active, check_action should return False
            app._input_callback = lambda v: None
            assert app.check_action_quit_workflow() is False
