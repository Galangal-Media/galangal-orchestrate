"""
Main Textual TUI application for workflow execution.

Layout:
┌──────────────────────────────────────────────────────────────────┐
│ Task: my-task  Stage: DEV (1/5)  Elapsed: 2:34  Turns: 5         │ Header
├──────────────────────────────────────────────────────────────────┤
│        ● PM ━ ● DESIGN ━ ● DEV ━ ○ TEST ━ ○ QA ━ ○ DONE          │ Progress
├────────────────────────────────────────────────────┬─────────────┤
│                                                    │ Files       │
│ Activity Log                                       │ ─────────── │
│ 11:30:00 • Starting stage...                       │ 📖 file.py  │
│ 11:30:01 📖 Read: file.py                          │ ✏️ test.py  │
│                                                    │             │
├────────────────────────────────────────────────────┴─────────────┤
│ ⠋ Running: waiting for API response                              │ Action
├──────────────────────────────────────────────────────────────────┤
│ ^Q Quit  ^D Verbose  ^F Files                                    │ Footer
└──────────────────────────────────────────────────────────────────┘
"""

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Footer, RichLog

from galangal.core.utils import debug_log
from galangal.ui.tui.adapters import PromptType, TUIAdapter, get_prompt_options
from galangal.ui.tui.mixins import WidgetAccessMixin
from galangal.ui.tui.modals import (
    GitHubIssueOption,
    GitHubIssueSelectModal,
    MultilineInputModal,
    PromptModal,
    QuestionAnswerModal,
    TextInputModal,
    UserQuestionsModal,
)
from galangal.ui.tui.types import (
    ActivityCategory,
    ActivityEntry,
    ActivityLevel,
    export_activity_log,
)
from galangal.ui.tui.widgets import (
    CurrentActionWidget,
    ErrorPanelWidget,
    FilesPanelWidget,
    HeaderWidget,
    StageProgressWidget,
)


class WorkflowTUIApp(WidgetAccessMixin, App[None]):
    """
    Textual TUI application for workflow execution.

    This is the main UI for interactive workflow execution. It displays:
    - Header: Task name, stage, attempt count, elapsed time, turn count
    - Progress bar: Visual representation of stage progression
    - Activity log: Real-time updates of AI actions
    - Files panel: List of files read/written
    - Current action: Spinner with current activity

    The app supports:
    - Modal prompts for approvals and choices (PromptModal)
    - Text input dialogs (TextInputModal, MultilineInputModal)
    - Verbose mode for raw JSON output (Ctrl+D)
    - Files panel toggle (Ctrl+F)
    - Graceful quit (Ctrl+Q)

    Threading Model:
        The TUI runs in the main thread (Textual event loop). All UI updates
        from background threads must use `call_from_thread()` to be thread-safe.

    Attributes:
        task_name: Name of the current task.
        current_stage: Current workflow stage.
        verbose: If True, show raw JSON output instead of activity log.
        _paused: Set to True when user requests pause.
        _workflow_result: Result string set by workflow thread.
    """
    ACTIVITY_LOG_MAX_ENTRIES = 5000
    RICH_LOG_MAX_LINES = 1000

    TITLE = "Galangal"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit_workflow", "^Q Quit", show=True, priority=True),
        Binding("ctrl+i", "interrupt_feedback", "^I Interrupt", show=True, priority=True),
        Binding("ctrl+n", "skip_stage", "^N Skip", show=True, priority=True),
        Binding("ctrl+b", "back_stage", "^B Back", show=True, priority=True),
        Binding("ctrl+e", "manual_edit", "^E Edit", show=True, priority=True),
        Binding("ctrl+d", "toggle_verbose", "^D Verbose", show=False, priority=True),
        Binding("ctrl+f", "toggle_files", "^F Files", show=False, priority=True),
    ]

    def __init__(
        self,
        task_name: str,
        initial_stage: str,
        max_retries: int = 5,
        hidden_stages: frozenset[str] | None = None,
        stage_durations: dict[str, int] | None = None,
        activity_log_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.task_name = task_name
        self.current_stage = initial_stage
        self._max_retries = max_retries
        self._hidden_stages = hidden_stages or frozenset()
        self._stage_durations = stage_durations or {}
        self.verbose = False
        self._start_time = time.time()
        self._attempt = 1
        self._turns = 0

        # Raw lines storage for verbose replay
        self._raw_lines: list[str] = []
        self._activity_entries: deque[ActivityEntry] = deque(
            maxlen=self.ACTIVITY_LOG_MAX_ENTRIES
        )
        self._activity_log_handle = None
        if activity_log_path:
            try:
                log_path = Path(activity_log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._activity_log_handle = open(
                    log_path, "a", encoding="utf-8", buffering=1
                )
            except OSError:
                self._activity_log_handle = None

        # Workflow control
        self._paused = False
        self._interrupt_requested = False
        self._skip_stage_requested = False
        self._back_stage_requested = False
        self._manual_edit_requested = False
        self._prompt_type = PromptType.NONE
        self._prompt_callback: Callable[..., None] | None = None
        self._active_prompt_screen: PromptModal | None = None
        self._workflow_result: str | None = None

        # Text input state
        self._input_callback: Callable[..., None] | None = None
        self._active_input_screen: TextInputModal | None = None
        self._files_visible = True

        # Remote action from hub (for remote approval)
        self._pending_remote_action: dict | None = None

    def compose(self) -> ComposeResult:
        with Container(id="workflow-root"):
            yield HeaderWidget(id="header")
            yield StageProgressWidget(id="progress")
            with Container(id="main-content"):
                yield ErrorPanelWidget(id="error-panel", classes="hidden")
                with Horizontal(id="content-area"):
                    with VerticalScroll(id="activity-container"):
                        yield RichLog(
                            id="activity-log",
                            highlight=True,
                            markup=True,
                            max_lines=self.RICH_LOG_MAX_LINES,
                        )
                    yield FilesPanelWidget(id="files-container")
            yield CurrentActionWidget(id="current-action")
            yield Footer()

    def on_mount(self) -> None:
        """Initialize widgets."""
        header = self.query_one("#header", HeaderWidget)
        header.task_name = self.task_name
        header.stage = self.current_stage
        header.attempt = self._attempt
        header.max_retries = self._max_retries

        progress = self.query_one("#progress", StageProgressWidget)
        progress.current_stage = self.current_stage
        progress.hidden_stages = self._hidden_stages
        progress.stage_durations = self._stage_durations

        # Start timers
        self.set_interval(1.0, self._update_elapsed)
        self.set_interval(0.1, self._update_spinner)

    def _update_elapsed(self) -> None:
        """Update elapsed time display."""
        elapsed = int(time.time() - self._start_time)
        if elapsed >= 3600:
            hours, remainder = divmod(elapsed, 3600)
            mins, secs = divmod(remainder, 60)
            elapsed_str = f"{hours}:{mins:02d}:{secs:02d}"
        else:
            mins, secs = divmod(elapsed, 60)
            elapsed_str = f"{mins}:{secs:02d}"

        try:
            header = self.query_one("#header", HeaderWidget)
            header.elapsed = elapsed_str
        except Exception:
            pass  # Widget may not exist during shutdown

    def _update_spinner(self) -> None:
        """Update action spinner."""
        try:
            action = self.query_one("#current-action", CurrentActionWidget)
            action.spinner_frame += 1
        except Exception:
            pass  # Widget may not exist during shutdown

    # -------------------------------------------------------------------------
    # Public API for workflow
    # -------------------------------------------------------------------------

    def update_stage(self, stage: str, attempt: int = 1) -> None:
        """Update current stage display."""
        self.current_stage = stage
        self._attempt = attempt

        def _update() -> None:
            header = self._safe_query("#header", HeaderWidget)
            if header:
                header.stage = stage
                header.attempt = attempt

            progress = self._safe_query("#progress", StageProgressWidget)
            if progress:
                progress.current_stage = stage

        self._safe_update(_update)

    def update_hidden_stages(self, hidden_stages: frozenset[str]) -> None:
        """Update which stages are hidden in the progress bar."""
        self._hidden_stages = hidden_stages

        def _update() -> None:
            progress = self._safe_query("#progress", StageProgressWidget)
            if progress:
                progress.hidden_stages = hidden_stages

        self._safe_update(_update)

    def set_status(self, status: str, detail: str = "") -> None:
        """Update current action display."""

        def _update() -> None:
            action = self._safe_query("#current-action", CurrentActionWidget)
            if action:
                action.action = status
                action.detail = detail

        self._safe_update(_update)

    def set_turns(self, turns: int) -> None:
        """Update turn count."""
        self._turns = turns

        def _update() -> None:
            header = self._safe_query("#header", HeaderWidget)
            if header:
                header.turns = turns

        self._safe_update(_update)

    def add_activity(
        self,
        activity: str,
        icon: str = "•",
        level: ActivityLevel = ActivityLevel.INFO,
        category: ActivityCategory = ActivityCategory.SYSTEM,
        details: str | None = None,
        verbose_only: bool = False,
    ) -> None:
        """
        Add activity to log.

        Args:
            activity: Message to display.
            icon: Icon prefix for the entry.
            level: Severity level (info, success, warning, error).
            category: Category for filtering (stage, validation, claude, file, system).
            details: Optional additional details for export.
            verbose_only: If True, only show in verbose mode (e.g., tool calls).
                         If False, show in both modes (e.g., Claude's text responses).
        """
        entry = ActivityEntry(
            message=activity,
            icon=icon,
            level=level,
            category=category,
            details=details,
            verbose_only=verbose_only,
        )
        self._activity_entries.append(entry)
        if self._activity_log_handle:
            try:
                self._activity_log_handle.write(entry.format_export() + "\n")
            except OSError:
                self._activity_log_handle = None

        def _add() -> None:
            # Filtering logic:
            # - In verbose mode: show everything
            # - In compact mode: only show items where verbose_only=False (AI responses)
            should_display = self.verbose or not verbose_only
            if should_display:
                log = self._safe_query("#activity-log", RichLog)
                if log:
                    log.write(entry.format_display())

        self._safe_update(_add)

    def add_file(self, action: str, path: str) -> None:
        """Add file to files panel."""

        def _add() -> None:
            files = self._safe_query("#files-container", FilesPanelWidget)
            if files:
                files.add_file(action, path)

        self._safe_update(_add)

    def show_message(
        self,
        message: str,
        style: str = "info",
        category: ActivityCategory = ActivityCategory.SYSTEM,
    ) -> None:
        """
        Show a styled message.

        Args:
            message: Message to display.
            style: Style name (info, success, error, warning).
            category: Category for filtering.
        """
        # Log errors and warnings to debug log
        if style in ("error", "warning"):
            debug_log(f"[TUI {style.upper()}]", content=message)

        icons = {"info": "ℹ", "success": "✓", "error": "✗", "warning": "⚠"}
        levels = {
            "info": ActivityLevel.INFO,
            "success": ActivityLevel.SUCCESS,
            "error": ActivityLevel.ERROR,
            "warning": ActivityLevel.WARNING,
        }
        icon = icons.get(style, "•")
        level = levels.get(style, ActivityLevel.INFO)
        self.add_activity(message, icon, level=level, category=category)

    def show_stage_complete(self, stage: str, success: bool, duration: int | None = None) -> None:
        """Show stage completion with optional duration."""
        if success:
            if duration is not None:
                # Format duration
                if duration >= 3600:
                    hours, remainder = divmod(duration, 3600)
                    mins, secs = divmod(remainder, 60)
                    duration_str = f"{hours}:{mins:02d}:{secs:02d}"
                else:
                    mins, secs = divmod(duration, 60)
                    duration_str = f"{mins}:{secs:02d}"
                self.show_message(
                    f"Stage {stage} completed ({duration_str})",
                    "success",
                    ActivityCategory.STAGE,
                )
            else:
                self.show_message(f"Stage {stage} completed", "success", ActivityCategory.STAGE)
        else:
            self.show_message(f"Stage {stage} failed", "error", ActivityCategory.STAGE)

    def update_stage_durations(self, durations: dict[str, int]) -> None:
        """Update stage durations display in progress widget."""

        def _update() -> None:
            progress = self._safe_query("#progress", StageProgressWidget)
            if progress:
                progress.stage_durations = durations

        self._safe_update(_update)

    def show_workflow_complete(self) -> None:
        """Show workflow completion banner."""
        self.add_activity("")
        self.add_activity("[bold #b8bb26]════════════════════════════════════════[/]", "")
        self.add_activity("[bold #b8bb26]           WORKFLOW COMPLETE            [/]", "")
        self.add_activity("[bold #b8bb26]════════════════════════════════════════[/]", "")
        self.add_activity("")

    def show_error(self, message: str, details: str | None = None) -> None:
        """
        Show error prominently in dedicated error panel.

        The error panel appears below the progress bar and above the activity log,
        making errors highly visible. Also logs the error to the activity log.

        Args:
            message: Short error message (displayed in bold red).
            details: Optional detailed error information (truncated if too long).
        """

        def _update() -> None:
            panel = self._safe_query("#error-panel", ErrorPanelWidget)
            if panel:
                panel.error = message
                panel.details = details
                panel.remove_class("hidden")

        self._safe_update(_update)

        # Also add to activity log
        self.add_activity(
            message,
            "✗",
            level=ActivityLevel.ERROR,
            category=ActivityCategory.SYSTEM,
            details=details,
        )

    def clear_error(self) -> None:
        """Clear the error panel display."""

        def _update() -> None:
            panel = self._safe_query("#error-panel", ErrorPanelWidget)
            if panel:
                panel.error = None
                panel.details = None
                panel.add_class("hidden")

        self._safe_update(_update)

    def show_prompt(
        self, prompt_type: PromptType, message: str, callback: Callable[..., None]
    ) -> None:
        """
        Show a modal prompt for user choice.

        Displays a modal dialog with options based on the prompt type.
        The callback is invoked with the user's selection when they
        choose an option or press Escape (returns "quit").

        This method is thread-safe and can be called from background threads.

        Args:
            prompt_type: Type of prompt determining available options.
            message: Message to display in the modal.
            callback: Function called with the selected option string.
        """
        self._prompt_type = prompt_type
        self._prompt_callback = callback

        options = get_prompt_options(prompt_type)

        def _show() -> None:
            def _handle(result: str | None) -> None:
                self._active_prompt_screen = None
                self._prompt_callback = None
                self._prompt_type = PromptType.NONE
                if result:
                    callback(result)

            screen = PromptModal(message, options)
            self._active_prompt_screen = screen
            self.push_screen(screen, _handle)

        self._safe_update(_show)

    def hide_prompt(self) -> None:
        """Hide prompt."""
        self._prompt_type = PromptType.NONE
        self._prompt_callback = None

        def _hide() -> None:
            if self._active_prompt_screen:
                self._active_prompt_screen.dismiss(None)
                self._active_prompt_screen = None

        self._safe_update(_hide)

    def show_text_input(self, label: str, default: str, callback: Callable[..., None]) -> None:
        """
        Show a single-line text input modal.

        Displays a modal with an input field. User submits with Enter,
        cancels with Escape. Callback receives the text or None if cancelled.

        This method is thread-safe and can be called from background threads.

        Args:
            label: Prompt label displayed above the input field.
            default: Default value pre-filled in the input.
            callback: Function called with input text or None if cancelled.
        """
        self._input_callback = callback

        def _show() -> None:
            def _handle(result: str | None) -> None:
                self._active_input_screen = None
                self._input_callback = None
                callback(result if result else None)

            screen = TextInputModal(label, default)
            self._active_input_screen = screen
            self.push_screen(screen, _handle)

        self._safe_update(_show)

    def hide_text_input(self) -> None:
        """Reset text input prompt."""
        self._input_callback = None

        def _hide() -> None:
            if self._active_input_screen:
                self._active_input_screen.dismiss(None)
                self._active_input_screen = None

        self._safe_update(_hide)

    def _dismiss_active_modal(self) -> None:
        """
        Dismiss any active modal (prompt, text input, or other).

        Called when a remote response arrives and we need to close
        the local modal that was waiting for input.
        """
        def _dismiss() -> None:
            # Dismiss prompt modals
            if self._active_prompt_screen:
                try:
                    self._active_prompt_screen.dismiss(None)
                except Exception:
                    pass
                self._active_prompt_screen = None

            # Dismiss text input modals
            if hasattr(self, "_active_input_screen") and self._active_input_screen:
                try:
                    self._active_input_screen.dismiss(None)
                except Exception:
                    pass
                self._active_input_screen = None

            # Clear callbacks
            self._prompt_callback = None
            self._input_callback = None
            self._prompt_type = PromptType.NONE

        self._safe_update(_dismiss)

    # -------------------------------------------------------------------------
    # Async prompt methods (simplified threading model)
    # -------------------------------------------------------------------------

    async def prompt_async(self, prompt_type: PromptType, message: str) -> str:
        """
        Show a modal prompt and await the result.

        This is the async version of show_prompt() that eliminates the need
        for callbacks and threading.Event coordination. Use this from async
        workflow code instead of the callback-based version.

        Also notifies the hub of the prompt and races local input against
        remote responses, allowing users to respond from either the TUI
        or the Hub UI.

        Args:
            prompt_type: Type of prompt determining available options.
            message: Message to display in the modal.

        Returns:
            The selected option string (e.g., "yes", "no", "quit").
        """
        # Notify hub of the prompt (non-fatal if fails)
        options = get_prompt_options(prompt_type)
        self._notify_hub_prompt(prompt_type, message, options)

        # Set up local prompt
        local_future: asyncio.Future[str] = asyncio.Future()

        def callback(result: str) -> None:
            if not local_future.done():
                local_future.set_result(result)

        # Show the prompt - this sets _active_prompt_screen synchronously
        # since we're in the Textual event loop context
        self._prompt_type = prompt_type
        self._prompt_callback = callback
        options_list = get_prompt_options(prompt_type)

        def _handle(result: str | None) -> None:
            self._active_prompt_screen = None
            self._prompt_callback = None
            self._prompt_type = PromptType.NONE
            if result:
                callback(result)

        screen = PromptModal(message, options_list)
        self._active_prompt_screen = screen
        self.push_screen(screen, _handle)

        # Small yield to ensure the screen is displayed before racing
        await asyncio.sleep(0)

        # Start remote response check (wrapped to handle errors gracefully)
        remote_task = asyncio.create_task(
            self._wait_for_remote_response_safe(prompt_type)
        )
        local_task = asyncio.ensure_future(local_future)

        try:
            done, pending = await asyncio.wait(
                [local_task, remote_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the loser
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Clear the hub prompt
            self._notify_hub_prompt_cleared()

            # Get the result - if remote task won but had an error, fall back to local
            completed_task = done.pop()
            try:
                result = completed_task.result()
            except Exception:
                # If the winning task failed, wait for the local prompt
                if completed_task == remote_task and not local_future.done():
                    result = await local_future
                else:
                    raise

            # If remote won, dismiss the local prompt
            if local_task in pending:
                self._dismiss_prompt_directly()

            return result

        except Exception:
            # If racing fails, fall back to simple local-only prompt
            self._notify_hub_prompt_cleared()
            if not local_future.done():
                return await local_future
            raise

    def _dismiss_prompt_directly(self) -> None:
        """
        Dismiss the active prompt screen directly.

        Use this when already in the Textual event loop context (e.g., from
        prompt_async) instead of hide_prompt() which uses call_from_thread.
        """
        self.add_activity(f"[DEBUG] _dismiss_prompt_directly called, screen={self._active_prompt_screen}", "🔍")
        self._prompt_type = PromptType.NONE
        self._prompt_callback = None
        if self._active_prompt_screen:
            screen = self._active_prompt_screen
            self._active_prompt_screen = None
            self.add_activity("[DEBUG] Calling pop_screen()", "🔍")
            # Use pop_screen instead of dismiss for more reliable dismissal
            try:
                self.pop_screen()
            except Exception as e:
                self.add_activity(f"[DEBUG] pop_screen failed: {e}", "🔍")
                # Fallback to dismiss
                try:
                    screen.dismiss(None)
                except Exception as e2:
                    self.add_activity(f"[DEBUG] dismiss also failed: {e2}", "🔍")

    def _notify_hub_prompt(
        self,
        prompt_type: PromptType,
        message: str,
        options: list,
        questions: list[str] | None = None,
    ) -> None:
        """Notify hub of a prompt being displayed."""
        try:
            from galangal.hub.hooks import notify_prompt

            # Determine relevant artifacts based on prompt type
            artifacts = self._get_artifacts_for_prompt(prompt_type)

            # Build context
            context = {
                "stage": self.current_stage,
                "task_name": self.task_name,
            }

            notify_prompt(
                prompt_type=prompt_type.value,
                message=message,
                options=options,
                artifacts=artifacts,
                context=context,
                questions=questions,
            )
        except Exception:
            # Hub notification failure is non-fatal
            pass

    def _notify_hub_prompt_cleared(self) -> None:
        """Notify hub that the prompt was answered/cleared."""
        try:
            from galangal.hub.hooks import notify_prompt_cleared

            notify_prompt_cleared()
        except Exception:
            pass

    def _get_artifacts_for_prompt(self, prompt_type: PromptType) -> list[str]:
        """Get list of relevant artifact names for a prompt type."""
        mapping = {
            PromptType.PLAN_APPROVAL: ["SPEC.md", "PLAN.md", "STAGE_PLAN.md"],
            PromptType.DESIGN_APPROVAL: ["DESIGN.md"],
            PromptType.COMPLETION: ["SUMMARY.md"],
            PromptType.STAGE_FAILURE: ["VALIDATION_REPORT.md"],
            PromptType.USER_DECISION: ["QA_REPORT.md", "TEST_REPORT.md"],
            PromptType.PREFLIGHT_RETRY: ["PREFLIGHT_REPORT.md"],
        }
        return mapping.get(prompt_type, [])

    async def _wait_for_remote_response_safe(self, prompt_type: PromptType) -> str:
        """
        Wait for a remote response from the hub, with error handling.

        This wrapper ensures that hub connection issues don't crash the prompt.
        If hub is not available, this will wait indefinitely (to be cancelled
        when local prompt completes).
        """
        try:
            return await self._wait_for_remote_response(prompt_type)
        except Exception:
            # If hub checking fails, wait forever (will be cancelled by local prompt)
            await asyncio.Event().wait()
            return ""  # Never reached, but keeps type checker happy

    async def _wait_for_remote_response(self, prompt_type: PromptType) -> str:
        """Wait for a remote response from the hub."""
        from galangal.hub.action_handler import get_action_handler

        handler = get_action_handler()

        while True:
            try:
                response = handler.peek_pending_response()
                if response and response.prompt_type == prompt_type.value:
                    # Consume the response
                    handler.get_pending_response()
                    self.add_activity(f"Remote response received from hub: {response.result}", "🌐")

                    # Always mark as remote response, include text_input if provided
                    self._pending_remote_action = {
                        "remote": True,
                        "text_input": response.text_input,
                    }

                    return response.result

                # Also check for legacy approve/reject actions for backwards compatibility
                action = handler.peek_pending_action()
                if action and action.task_name == self.task_name:
                    from galangal.hub.action_handler import ActionType

                    if action.action_type == ActionType.APPROVE:
                        handler.get_pending_action()
                        self.add_activity("Remote approval received from hub", "🌐")
                        self._pending_remote_action = {"remote": True}
                        return "yes"
                    elif action.action_type == ActionType.REJECT:
                        handler.get_pending_action()
                        reason = action.data.get("reason", "")
                        self.add_activity(f"Remote rejection from hub: {reason}", "🌐")
                        self._pending_remote_action = {"remote": True, "text_input": reason}
                        return "no"
                    elif action.action_type == ActionType.SKIP:
                        handler.get_pending_action()
                        self.add_activity("Remote skip received from hub", "🌐")
                        self._pending_remote_action = {"remote": True}
                        return "skip"
            except Exception:
                # If there's an error checking, just continue polling
                pass

            await asyncio.sleep(0.3)  # Poll every 300ms

    async def text_input_async(self, label: str, default: str = "") -> str | None:
        """
        Show a text input modal and await the result.

        This is the async version of show_text_input() that eliminates the need
        for callbacks and threading.Event coordination. Also notifies the Hub
        and races local vs remote input.

        Args:
            label: Prompt label displayed above the input field.
            default: Default value pre-filled in the input.

        Returns:
            The entered text, or None if cancelled.
        """
        from galangal.ui.tui.modals import PromptOption

        # Notify Hub of text input prompt
        self._notify_hub_prompt(
            PromptType.TEXT_INPUT_PROMPT,
            label,
            [PromptOption("1", "Submit", "submit", "#b8bb26")],
        )

        local_future: asyncio.Future[str | None] = asyncio.Future()

        def callback(result: str | None) -> None:
            if not local_future.done():
                local_future.set_result(result)

        self.show_text_input(label, default, callback)

        # Race local vs remote
        remote_task = asyncio.create_task(
            self._wait_for_remote_response_safe(PromptType.TEXT_INPUT_PROMPT)
        )
        local_task = asyncio.ensure_future(local_future)

        try:
            done, pending = await asyncio.wait(
                [local_task, remote_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            self._notify_hub_prompt_cleared()

            completed_task = done.pop()
            if completed_task == remote_task:
                # Remote won - check for text_input
                remote_action = getattr(self, "_pending_remote_action", None)
                if remote_action and remote_action.get("text_input"):
                    self.add_activity("Remote text input received from hub", "🌐")
                    # Dismiss local modal if shown
                    self._dismiss_active_modal()
                    return remote_action.get("text_input")
                elif remote_action:
                    # Remote sent cancel or no text
                    result = completed_task.result()
                    if result == "cancel":
                        self._dismiss_active_modal()
                        return None
            # Local completed or remote had no text_input
            return local_future.result() if local_future.done() else None
        except Exception:
            self._notify_hub_prompt_cleared()
            return await local_future

    async def multiline_input_async(self, label: str, default: str = "") -> str | None:
        """
        Show a multiline input modal and await the result.

        This is the async version of show_multiline_input() that eliminates
        the need for callbacks and threading.Event coordination. Also notifies Hub
        and races local vs remote input.

        Args:
            label: Prompt label displayed above the text area.
            default: Default value pre-filled in the text area.

        Returns:
            The entered text, or None if cancelled.
        """
        from galangal.ui.tui.modals import PromptOption

        # Notify Hub of multiline input prompt
        self._notify_hub_prompt(
            PromptType.MULTILINE_INPUT,
            label,
            [PromptOption("1", "Submit", "submit", "#b8bb26")],
        )

        local_future: asyncio.Future[str | None] = asyncio.Future()

        def callback(result: str | None) -> None:
            if not local_future.done():
                local_future.set_result(result)

        self.show_multiline_input(label, default, callback)

        # Race local vs remote
        remote_task = asyncio.create_task(
            self._wait_for_remote_response_safe(PromptType.MULTILINE_INPUT)
        )
        local_task = asyncio.ensure_future(local_future)

        try:
            done, pending = await asyncio.wait(
                [local_task, remote_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            self._notify_hub_prompt_cleared()

            completed_task = done.pop()
            if completed_task == remote_task:
                # Remote won - check for text_input
                remote_action = getattr(self, "_pending_remote_action", None)
                if remote_action and remote_action.get("text_input"):
                    self.add_activity("Remote multiline input received from hub", "🌐")
                    # Dismiss local modal if shown
                    self._dismiss_active_modal()
                    return remote_action.get("text_input")
                elif remote_action:
                    # Remote sent cancel or no text
                    result = completed_task.result()
                    if result == "cancel":
                        self._dismiss_active_modal()
                        return None
            # Local completed or remote had no text_input
            return local_future.result() if local_future.done() else None
        except Exception:
            self._notify_hub_prompt_cleared()
            return await local_future

    # -------------------------------------------------------------------------
    # Discovery Q&A async methods
    # -------------------------------------------------------------------------

    async def question_answer_session_async(self, questions: list[str]) -> list[str] | None:
        """
        Show a Q&A modal and await all answers.

        Displays all questions and collects answers one at a time.
        User answers each question sequentially. Also notifies Hub and races
        local vs remote input - user can answer from CLI or Hub.

        Args:
            questions: List of questions to ask.

        Returns:
            List of answers (same length as questions), or None if cancelled.
        """
        from galangal.ui.tui.modals import PromptOption

        # Notify Hub of Q&A session with questions
        self._notify_hub_prompt(
            PromptType.DISCOVERY_QA,
            f"Discovery Q&A ({len(questions)} questions)",
            [
                PromptOption("1", "Submit Answers", "submit", "#b8bb26"),
                PromptOption("2", "Skip (Answer in CLI)", "skip", "#83a598"),
            ],
            questions=questions,
        )

        local_future: asyncio.Future[list[str] | None] = asyncio.Future()

        def _show() -> None:
            def _handle(result: list[str] | None) -> None:
                if not local_future.done():
                    local_future.set_result(result)

            screen = QuestionAnswerModal(questions)
            self._active_prompt_screen = screen
            self.push_screen(screen, _handle)

        self._safe_update(_show)

        # Race local vs remote
        remote_task = asyncio.create_task(
            self._wait_for_remote_response_safe(PromptType.DISCOVERY_QA)
        )
        local_task = asyncio.ensure_future(local_future)

        try:
            done, pending = await asyncio.wait(
                [local_task, remote_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            self._notify_hub_prompt_cleared()

            completed_task = done.pop()
            if completed_task == remote_task:
                # Remote won - check for text_input with answers
                remote_action = getattr(self, "_pending_remote_action", None)
                if remote_action and remote_action.get("text_input"):
                    self.add_activity("Remote Q&A answers received from hub", "🌐")
                    # Dismiss local modal if shown
                    self._dismiss_active_modal()
                    # Parse answers from text_input (format: "1. answer1\n2. answer2\n...")
                    text_input = remote_action.get("text_input", "")
                    answers = self._parse_qa_answers(text_input, len(questions))
                    return answers
                elif remote_action:
                    result = completed_task.result()
                    if result == "skip":
                        # User wants to answer in CLI - continue with local modal
                        self.add_activity("User chose to answer in CLI", "🌐")
                        # Wait for local modal to complete
                        return await local_future
                    elif result == "cancel":
                        self._dismiss_active_modal()
                        return None
            # Local completed
            return local_future.result() if local_future.done() else None
        except Exception:
            self._notify_hub_prompt_cleared()
            return await local_future

    def _parse_qa_answers(self, text_input: str, num_questions: int) -> list[str]:
        """
        Parse Q&A answers from Hub text input.

        Expected format: "1. answer1\\n2. answer2\\n..."
        Falls back to splitting by newlines if numbered format not found.

        Args:
            text_input: The combined answers text from Hub.
            num_questions: Expected number of answers.

        Returns:
            List of answer strings (padded with empty strings if needed).
        """
        import re

        lines = text_input.strip().split("\n")
        answers: list[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Try to match "1. answer" format
            match = re.match(r"^\d+\.\s*(.*)$", line)
            if match:
                answers.append(match.group(1).strip())
            else:
                # Just use the whole line
                answers.append(line)

        # Pad with empty strings if needed
        while len(answers) < num_questions:
            answers.append("")

        return answers[:num_questions]

    async def ask_yes_no_async(self, prompt: str) -> bool:
        """
        Show a simple yes/no prompt and await the result.

        Args:
            prompt: Question to ask.

        Returns:
            True if user selected yes, False otherwise.
        """
        result = await self.prompt_async(PromptType.YES_NO, prompt)
        return result == "yes"

    async def get_user_questions_async(self) -> list[str] | None:
        """
        Show a modal for user to enter their own questions.

        Returns:
            List of questions (one per line), or None if cancelled/empty.
        """
        future: asyncio.Future[list[str] | None] = asyncio.Future()

        def _show() -> None:
            def _handle(result: list[str] | None) -> None:
                if not future.done():
                    future.set_result(result)

            screen = UserQuestionsModal()
            self.push_screen(screen, _handle)

        self._safe_update(_show)
        return await future

    async def select_github_issue_async(self, issues: list[tuple[int, str]]) -> int | None:
        """
        Show a modal for selecting a GitHub issue.

        Also notifies the Hub so the issue selection can happen remotely.

        Args:
            issues: List of (issue_number, title) tuples.

        Returns:
            Selected issue number, or None if cancelled.
        """
        from galangal.ui.tui.modals import PromptOption

        # Notify Hub of the prompt with issues as options
        hub_options = [
            PromptOption(str(num), title[:50], str(num), "#83a598")
            for num, title in issues[:10]  # Limit to 10 for Hub display
        ]
        self._notify_hub_prompt(
            PromptType.GITHUB_ISSUE_SELECT,
            f"Select GitHub issue ({len(issues)} available)",
            hub_options,
        )

        # Set up racing between local and remote
        local_future: asyncio.Future[int | None] = asyncio.Future()

        def local_callback(result: int | None) -> None:
            if not local_future.done():
                local_future.set_result(result)

        # Show local modal
        def _show() -> None:
            options = [GitHubIssueOption(num, title) for num, title in issues]
            screen = GitHubIssueSelectModal(options)
            self.push_screen(screen, local_callback)

        self._safe_update(_show)

        # Small yield to ensure screen is displayed
        await asyncio.sleep(0)

        # Race local vs remote
        remote_task = asyncio.create_task(
            self._wait_for_remote_issue_select()
        )
        local_task = asyncio.ensure_future(local_future)

        try:
            done, pending = await asyncio.wait(
                [local_task, remote_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the loser
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Clear the hub prompt
            self._notify_hub_prompt_cleared()

            # Get the result
            completed_task = done.pop()
            try:
                result = completed_task.result()
            except Exception:
                if completed_task == remote_task and not local_future.done():
                    result = await local_future
                else:
                    raise

            # If remote won, dismiss the local modal
            if local_task in pending:
                # Pop the GitHub issue select screen
                try:
                    self.pop_screen()
                except Exception:
                    pass

            return result

        except Exception:
            self._notify_hub_prompt_cleared()
            if not local_future.done():
                return await local_future
            raise

    async def _wait_for_remote_issue_select(self) -> int | None:
        """Wait for a remote GitHub issue selection from the hub."""
        from galangal.hub.action_handler import get_action_handler

        handler = get_action_handler()

        while True:
            try:
                response = handler.peek_pending_response()
                if response and response.prompt_type == PromptType.GITHUB_ISSUE_SELECT.value:
                    handler.get_pending_response()
                    self.add_activity(f"Remote issue selection from hub: #{response.result}", "🌐")
                    try:
                        return int(response.result)
                    except ValueError:
                        return None
            except Exception:
                pass

            await asyncio.sleep(0.3)

    def show_multiline_input(self, label: str, default: str, callback: Callable[..., None]) -> None:
        """
        Show a multi-line text input modal.

        Displays a modal with a TextArea for multi-line input (task descriptions,
        feedback, rejection reasons). User submits with Ctrl+S, cancels with Escape.
        Callback receives the text or None if cancelled.

        This method is thread-safe and can be called from background threads.

        Args:
            label: Prompt label displayed above the text area.
            default: Default value pre-filled in the text area.
            callback: Function called with input text or None if cancelled.
        """
        self._input_callback = callback

        def _show() -> None:
            def _handle(result: str | None) -> None:
                self._active_input_screen = None
                self._input_callback = None
                callback(result if result else None)

            screen = MultilineInputModal(label, default)
            self._active_input_screen = screen
            self.push_screen(screen, _handle)

        self._safe_update(_show)

    def show_github_issue_select(self, issues: list[tuple[int, str]], callback: Callable) -> None:
        """
        Show a modal for selecting a GitHub issue.

        This method is thread-safe and can be called from background threads.

        Args:
            issues: List of (issue_number, title) tuples.
            callback: Function called with selected issue number or None if cancelled.
        """

        def _show() -> None:
            def _handle(result: int | None) -> None:
                callback(result)

            options = [GitHubIssueOption(num, title) for num, title in issues]
            screen = GitHubIssueSelectModal(options)
            self.push_screen(screen, _handle)

        self._safe_update(_show)

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def _text_input_active(self) -> bool:
        """Check if text input is currently active and should capture keys."""
        return self._input_callback is not None or self._active_input_screen is not None

    def check_action_quit_workflow(self) -> bool:
        return not self._text_input_active()

    def check_action_interrupt_feedback(self) -> bool:
        return not self._text_input_active()

    def check_action_skip_stage(self) -> bool:
        return not self._text_input_active()

    def check_action_back_stage(self) -> bool:
        return not self._text_input_active()

    def check_action_manual_edit(self) -> bool:
        return not self._text_input_active()

    def check_action_toggle_verbose(self) -> bool:
        return not self._text_input_active()

    def action_quit_workflow(self) -> None:
        if self._active_prompt_screen:
            self._active_prompt_screen.dismiss("quit")
            return
        if self._prompt_callback:
            callback = self._prompt_callback
            self.hide_prompt()
            callback("quit")
            return
        self._paused = True
        self._workflow_result = "paused"
        self.exit()

    def action_interrupt_feedback(self) -> None:
        """Interrupt current stage and request rollback to DEV with feedback."""
        if self._active_prompt_screen or self._prompt_callback:
            # Don't interrupt during prompts
            return
        self._interrupt_requested = True
        self._paused = True  # Stop Claude execution

    def action_skip_stage(self) -> None:
        """Skip the current stage and advance to the next one."""
        if self._active_prompt_screen or self._prompt_callback:
            return
        self._skip_stage_requested = True
        self._paused = True

    def action_back_stage(self) -> None:
        """Go back to the previous stage."""
        if self._active_prompt_screen or self._prompt_callback:
            return
        self._back_stage_requested = True
        self._paused = True

    def action_manual_edit(self) -> None:
        """Pause workflow for manual editing, then resume."""
        if self._active_prompt_screen or self._prompt_callback:
            return
        self._manual_edit_requested = True
        self._paused = True

    def add_raw_line(self, line: str) -> None:
        """Store raw line and display if in verbose mode."""
        # Store for replay (keep last 500 lines)
        self._raw_lines.append(line)
        if len(self._raw_lines) > 500:
            self._raw_lines = self._raw_lines[-500:]

        def _add() -> None:
            if self.verbose:
                log = self._safe_query("#activity-log", RichLog)
                if log:
                    display = line.strip()[:150]  # Truncate to 150 chars
                    log.write(f"[#7c6f64]{display}[/]")

        self._safe_update(_add)

    def action_toggle_verbose(self) -> None:
        self.verbose = not self.verbose
        log = self.query_one("#activity-log", RichLog)
        log.clear()

        if self.verbose:
            log.write("[#83a598]Switched to VERBOSE mode - showing all activity[/]")
            # Replay last 50 activity entries (includes tool calls)
            for entry in list(self._activity_entries)[-50:]:
                log.write(entry.format_display())
        else:
            log.write("[#b8bb26]Switched to COMPACT mode - showing AI responses only[/]")
            # Replay recent activity entries, excluding verbose_only items
            non_verbose = [e for e in self._activity_entries if not e.verbose_only]
            for entry in non_verbose[-30:]:
                log.write(entry.format_display())

    def action_toggle_files(self) -> None:
        self._files_visible = not self._files_visible
        files = self.query_one("#files-container", FilesPanelWidget)
        activity = self.query_one("#activity-container", VerticalScroll)

        if self._files_visible:
            files.display = True
            files.styles.width = "25%"
            activity.styles.width = "75%"
        else:
            files.display = False
            activity.styles.width = "100%"

    # -------------------------------------------------------------------------
    # Activity log access
    # -------------------------------------------------------------------------

    @property
    def activity_entries(self) -> list[ActivityEntry]:
        """Get all activity entries for filtering or export."""
        return list(self._activity_entries)

    def export_activity_log(self, path: str | Path) -> None:
        """
        Export activity log to a file.

        Args:
            path: File path to write the log to.
        """
        export_activity_log(list(self._activity_entries), Path(path))

    def get_entries_by_level(self, level: ActivityLevel) -> list[ActivityEntry]:
        """Filter entries by severity level."""
        return [e for e in self._activity_entries if e.level == level]

    def get_entries_by_category(self, category: ActivityCategory) -> list[ActivityEntry]:
        """Filter entries by category."""
        return [e for e in self._activity_entries if e.category == category]

    def on_shutdown(self) -> None:
        if self._activity_log_handle:
            try:
                self._activity_log_handle.close()
            except OSError:
                pass


class StageTUIApp(WorkflowTUIApp):
    """
    Single-stage TUI application for `galangal run` command.

    A simplified version of WorkflowTUIApp that executes a single stage
    and exits. Used for manual stage re-runs outside the normal workflow.

    The stage execution happens in a background thread, with the TUI
    displaying progress until completion.
    """

    def __init__(
        self,
        task_name: str,
        stage: str,
        branch: str,
        attempt: int,
        prompt: str,
    ):
        super().__init__(task_name, stage)
        self.branch = branch
        self._attempt = attempt
        self.prompt = prompt
        self.result: tuple[bool, str] = (False, "")

    def on_mount(self) -> None:
        super().on_mount()
        self._worker_thread = threading.Thread(target=self._execute_stage, daemon=True)
        self._worker_thread.start()

    def _execute_stage(self) -> None:
        from galangal.ai import get_backend_with_fallback
        from galangal.config.loader import get_config

        config = get_config()
        backend = get_backend_with_fallback(config.ai.default, config=config)
        ui = TUIAdapter(self)
        max_turns = backend.config.max_turns if backend.config else 200

        self.result = backend.invoke(
            prompt=self.prompt,
            timeout=14400,
            max_turns=max_turns,
            ui=ui,
        )

        success, _ = self.result
        if success:
            self.call_from_thread(self.add_activity, "[#b8bb26]Stage completed[/]", "✓")
        else:
            self.call_from_thread(self.add_activity, "[#fb4934]Stage failed[/]", "✗")

        self.call_from_thread(self.set_timer, 1.5, self.exit)
