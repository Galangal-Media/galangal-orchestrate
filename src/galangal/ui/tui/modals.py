"""
Modal screens for TUI prompts and inputs.
"""

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static, TextArea


@dataclass(frozen=True)
class PromptOption:
    """Option for a prompt modal."""

    key: str
    label: str
    result: str
    color: str


class PromptModal(ModalScreen):
    """Modal prompt for multi-choice selections."""

    CSS = """
    PromptModal {
        align: center middle;
        layout: vertical;
    }

    #prompt-dialog {
        width: 90%;
        max-width: 120;
        min-width: 50;
        max-height: 80%;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
        overflow-y: auto;
    }

    #prompt-message {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        text-wrap: wrap;
    }

    #prompt-options {
        color: #ebdbb2;
    }

    #prompt-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

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


class TextInputModal(ModalScreen):
    """Modal for collecting short text input."""

    CSS = """
    TextInputModal {
        align: center middle;
        layout: vertical;
    }

    #text-input-dialog {
        width: 70%;
        max-width: 80;
        min-width: 40;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
    }

    #text-input-label {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        text-wrap: wrap;
    }

    #text-input-field {
        width: 100%;
    }

    #text-input-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

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


class QuestionAnswerModal(ModalScreen):
    """Modal for Q&A sessions - displays questions and collects answers sequentially."""

    CSS = """
    QuestionAnswerModal {
        align: center middle;
        layout: vertical;
    }

    #qa-dialog {
        width: 90%;
        max-width: 100;
        min-width: 60;
        max-height: 85%;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
        overflow-y: auto;
    }

    #qa-title {
        color: #fe8019;
        text-style: bold;
        margin-bottom: 1;
    }

    #qa-questions {
        color: #a89984;
        margin-bottom: 1;
        padding: 0 1;
    }

    #qa-current-question {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        padding: 0 1;
    }

    #qa-input-field {
        width: 100%;
        margin-bottom: 1;
    }

    #qa-progress {
        color: #7c6f64;
    }

    #qa-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

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
        questions_display = "\n".join(
            f"  {i+1}. {q}" for i, q in enumerate(self._questions)
        )

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


class UserQuestionsModal(ModalScreen):
    """Modal for user to enter their own questions."""

    CSS = """
    UserQuestionsModal {
        align: center middle;
        layout: vertical;
    }

    #user-questions-dialog {
        width: 90%;
        max-width: 100;
        min-width: 50;
        height: auto;
        max-height: 80%;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
    }

    #user-questions-label {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        text-wrap: wrap;
    }

    #user-questions-field {
        width: 100%;
        height: 10;
        min-height: 6;
        background: #282828;
        border: solid #504945;
    }

    #user-questions-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+s", "submit", "Submit", show=True, priority=True),
    ]

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="user-questions-dialog"):
            yield Static(
                "Enter your questions (one per line):",
                id="user-questions-label"
            )
            yield TextArea("", id="user-questions-field")
            yield Static(
                "Ctrl+S to submit, Esc to cancel",
                id="user-questions-hint"
            )

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


class MultilineInputModal(ModalScreen):
    """Modal for collecting multi-line text input (task descriptions, briefs)."""

    CSS = """
    MultilineInputModal {
        align: center middle;
        layout: vertical;
    }

    #multiline-input-dialog {
        width: 90%;
        max-width: 100;
        min-width: 50;
        height: auto;
        max-height: 80%;
        background: #3c3836;
        border: round #504945;
        padding: 1 2;
        layout: vertical;
    }

    #multiline-input-label {
        color: #ebdbb2;
        text-style: bold;
        margin-bottom: 1;
        text-wrap: wrap;
    }

    #multiline-input-field {
        width: 100%;
        height: 12;
        min-height: 6;
        background: #282828;
        border: solid #504945;
    }

    #multiline-input-hint {
        color: #7c6f64;
        margin-top: 1;
    }
    """

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
