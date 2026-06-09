"""Tests for strip_code_fences (keeps markdown out of commit messages)."""

from galangal.core.utils import strip_code_fences


def test_strips_whole_message_fence():
    fenced = "```\nfeat(sms): add SMS resale\n\n- bullet one\n- bullet two\n```"
    out = strip_code_fences(fenced)
    assert out.startswith("feat(sms):")
    assert "```" not in out
    assert "- bullet two" in out


def test_strips_language_tagged_fence():
    assert strip_code_fences("```text\nfix: bug\n```") == "fix: bug"


def test_plain_text_unchanged():
    msg = "feat: x\n\n- y"
    assert strip_code_fences(msg) == msg


def test_single_line_backticked():
    assert strip_code_fences("```feat: x") == "feat: x"


def test_empty_returns_empty():
    assert strip_code_fences("") == ""
    assert strip_code_fences("   ") == ""
