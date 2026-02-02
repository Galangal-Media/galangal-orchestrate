"""
Modal screens for TUI prompts and inputs.
"""

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea


class _KeylessScroll(VerticalScroll):
    """VerticalScroll that doesn't capture arrow keys, allowing parent to handle them."""

    BINDINGS = []
    can_focus = False


@dataclass(frozen=True)
class PromptOption:
    """Option for a prompt modal."""

    key: str
    label: str
    result: str
    color: str


class PromptModal(ModalScreen[str]):
    """Modal prompt for multi-choice selections."""

    CSS_PATH = "styles/modals.tcss"

    BINDINGS = [
        Binding("1", "choose_1", show=False),
        Binding("2", "choose_2", show=False),
        Binding("3", "choose_3", show=False),
        Binding("4", "choose_4", show=False),
        Binding("5", "choose_5", show=False),
        Binding("6", "choose_6", show=False),
        Binding("y", "choose_yes", show=False),
        Binding("n", "choose_no", show=False),
        Binding("q", "choose_quit", show=False),
        Binding("escape", "choose_quit", show=False),
    ]

    def __init__(self, message: str, options: list[PromptOption]):
        super().__init__()
        self._message = message
        self._options = options
        self._key_map = {option.key: option.result for option in options}

    def compose(self) -> ComposeResult:
        options_text = "\n".join(
            f"[{option.color}]{option.key}[/] {option.label}" for option in self._options
        )
        # Dynamic hint based on number of options
        max_key = max((int(o.key) for o in self._options if o.key.isdigit()), default=3)
        hint = f"Press 1-{max_key} to choose, Esc to cancel"
        with Vertical(id="prompt-dialog"):
            yield Static(self._message, id="prompt-message")
            yield Static(Text.from_markup(options_text), id="prompt-options")
            yield Static(hint, id="prompt-hint")

    def _submit_key(self, key: str) -> None:
        result = self._key_map.get(key)
        if result:
            self.dismiss(result)

    def action_choose_1(self) -> None:
        self._submit_key("1")

    def action_choose_2(self) -> None:
        self._submit_key("2")

    def action_choose_3(self) -> None:
        self._submit_key("3")

    def action_choose_4(self) -> None:
        self._submit_key("4")

    def action_choose_5(self) -> None:
        self._submit_key("5")

    def action_choose_6(self) -> None:
        self._submit_key("6")

    def action_choose_yes(self) -> None:
        self.dismiss("yes")

    def action_choose_no(self) -> None:
        self.dismiss("no")

    def action_choose_quit(self) -> None:
        self.dismiss("quit")


class TextInputModal(ModalScreen[str | None]):
    """Modal for collecting short text input."""

    CSS_PATH = "styles/modals.tcss"

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    def __init__(self, label: str, default: str = ""):
        super().__init__()
        self._label = label
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="text-input-dialog"):
            yield Static(self._label, id="text-input-label")
            yield Input(value=self._default, placeholder=self._label, id="text-input-field")
            yield Static("Press Enter to submit, Esc to cancel", id="text-input-hint")

    def on_mount(self) -> None:
        field = self.query_one("#text-input-field", Input)
        self.set_focus(field)
        field.cursor_position = len(field.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "text-input-field":
            value = event.value.strip()
            self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class QuestionAnswerModal(ModalScreen[list[str] | None]):
    """Modal for Q&A sessions - displays questions and collects answers sequentially."""

    CSS_PATH = "styles/modals.tcss"

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    def __init__(self, questions: list[str]):
        super().__init__()
        self._questions = questions
        self._answers: list[str] = []
        self._current_index = 0

    def compose(self) -> ComposeResult:
        # Format all questions for display
        questions_display = "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(self._questions))

        with Vertical(id="qa-dialog"):
            yield Static("Discovery Questions", id="qa-title")
            yield Static(questions_display, id="qa-questions")
            yield Static(self._get_current_question_text(), id="qa-current-question")
            yield Input(placeholder="Your answer...", id="qa-input-field")
            yield Static(self._get_progress_text(), id="qa-progress")
            yield Static("Press Enter to submit answer, Esc to cancel", id="qa-hint")

    def _get_current_question_text(self) -> str:
        if self._current_index < len(self._questions):
            return f"→ Q{self._current_index + 1}: {self._questions[self._current_index]}"
        return "All questions answered!"

    def _get_progress_text(self) -> str:
        return f"Question {self._current_index + 1} of {len(self._questions)}"

    def on_mount(self) -> None:
        field = self.query_one("#qa-input-field", Input)
        self.set_focus(field)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "qa-input-field":
            answer = event.value.strip()
            if not answer:
                return  # Require non-empty answer

            self._answers.append(answer)
            self._current_index += 1

            if self._current_index >= len(self._questions):
                # All questions answered
                self.dismiss(self._answers)
            else:
                # Update UI for next question
                self._update_question_display()
                event.input.value = ""

    def _update_question_display(self) -> None:
        question_widget = self.query_one("#qa-current-question", Static)
        question_widget.update(self._get_current_question_text())

        progress_widget = self.query_one("#qa-progress", Static)
        progress_widget.update(self._get_progress_text())

    def action_cancel(self) -> None:
        self.dismiss(None)


class UserQuestionsModal(ModalScreen[list[str] | None]):
    """Modal for user to enter their own questions."""

    CSS_PATH = "styles/modals.tcss"

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "submit", "Submit", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="user-questions-dialog"):
            yield Static("Enter your questions (one per line):", id="user-questions-label")
            yield TextArea("", id="user-questions-field")
            yield Static("Ctrl+S to submit, Esc to cancel", id="user-questions-hint")

    def on_mount(self) -> None:
        field = self.query_one("#user-questions-field", TextArea)
        self.set_focus(field)

    def action_submit(self) -> None:
        field = self.query_one("#user-questions-field", TextArea)
        text = field.text.strip()
        if not text:
            self.dismiss(None)
            return

        # Parse questions (one per line, skip empty lines)
        questions = [q.strip() for q in text.split("\n") if q.strip()]
        self.dismiss(questions if questions else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MultilineInputModal(ModalScreen[str | None]):
    """Modal for collecting multi-line text input (task descriptions, briefs)."""

    CSS_PATH = "styles/modals.tcss"

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "submit", "Submit", show=True, priority=True),
    ]

    def __init__(self, label: str, default: str = ""):
        super().__init__()
        self._label = label
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="multiline-input-dialog"):
            yield Static(self._label, id="multiline-input-label")
            yield TextArea(self._default, id="multiline-input-field")
            yield Static("Ctrl+S to submit, Esc to cancel", id="multiline-input-hint")

    def on_mount(self) -> None:
        field = self.query_one("#multiline-input-field", TextArea)
        self.set_focus(field)
        # Move cursor to end of text
        field.move_cursor(field.document.end)

    def action_submit(self) -> None:
        field = self.query_one("#multiline-input-field", TextArea)
        value = field.text.strip()
        self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


@dataclass
class GitHubIssueOption:
    """A GitHub issue option for selection."""

    number: int
    title: str


class _IssueItem(Static):
    """A single issue item in the selection list."""

    def __init__(self, issue_number: int, title: str, selected: bool = False) -> None:
        self.issue_number = issue_number
        self.title = title
        super().__init__(self._render(selected))

    def _render(self, selected: bool) -> Text:
        prefix = "→ " if selected else "  "
        color = "#b8bb26" if selected else "#ebdbb2"
        # Truncate title if too long (80 chars to fit in modal)
        title = self.title[:80] + "..." if len(self.title) > 80 else self.title
        return Text.from_markup(f"[{color}]{prefix}#{self.issue_number} {title}[/]")

    def set_selected(self, selected: bool) -> None:
        self.update(self._render(selected))


class GitHubIssueSelectModal(ModalScreen[int | None]):
    """Modal for selecting a GitHub issue from a list."""

    CSS_PATH = "styles/modals.tcss"

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("up", "move_up", show=False, priority=True),
        Binding("down", "move_down", show=False, priority=True),
        Binding("enter", "select", show=False),
        Binding("k", "move_up", show=False),
        Binding("j", "move_down", show=False),
    ]

    def __init__(self, issues: list[GitHubIssueOption]):
        super().__init__()
        self._issues = issues
        self._selected_index = 0
        self._issue_widgets: list[_IssueItem] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="issue-select-dialog"):
            yield Static("Select GitHub Issue", id="issue-select-title")
            with _KeylessScroll(id="issue-select-scroll"):
                if not self._issues:
                    yield Static("[dim]No issues found[/]", id="issue-select-empty")
                else:
                    for i, issue in enumerate(self._issues):
                        widget = _IssueItem(
                            issue.number, issue.title, selected=(i == 0)
                        )
                        widget.id = f"issue-item-{i}"
                        self._issue_widgets.append(widget)
                        yield widget
            yield Static(
                "↑/↓ or j/k to navigate, Enter to select, Esc to cancel", id="issue-select-hint"
            )

    def _update_selection(self, old_index: int, new_index: int) -> None:
        """Update the visual selection and scroll to keep it visible."""
        if self._issue_widgets:
            self._issue_widgets[old_index].set_selected(False)
            self._issue_widgets[new_index].set_selected(True)
            # Scroll the selected widget into view
            self._issue_widgets[new_index].scroll_visible()

    def action_move_up(self) -> None:
        if self._selected_index > 0:
            old_index = self._selected_index
            self._selected_index -= 1
            self._update_selection(old_index, self._selected_index)

    def action_move_down(self) -> None:
        if self._selected_index < len(self._issues) - 1:
            old_index = self._selected_index
            self._selected_index += 1
            self._update_selection(old_index, self._selected_index)

    def action_select(self) -> None:
        if self._issues:
            self.dismiss(self._issues[self._selected_index].number)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
