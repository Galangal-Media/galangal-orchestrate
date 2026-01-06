"""
Gemini backend implementation (stub for future use).
"""

from typing import Optional, TYPE_CHECKING

from galangal.ai.base import AIBackend

if TYPE_CHECKING:
    from galangal.ui.tui import StageUI


class GeminiBackend(AIBackend):
    """
    Gemini backend (stub implementation).

    TODO: Implement when Gemini CLI or API support is added.
    """

    @property
    def name(self) -> str:
        return "gemini"

    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui: Optional["StageUI"] = None,
    ) -> tuple[bool, str]:
        """Invoke Gemini with a prompt."""
        # TODO: Implement Gemini invocation
        return False, "Gemini backend not yet implemented"

    def generate_text(self, prompt: str, timeout: int = 30) -> str:
        """Simple text generation with Gemini."""
        # TODO: Implement Gemini text generation
        return ""
