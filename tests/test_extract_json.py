"""Tests for the tolerant JSON extractor used on backend/CLI output."""

from galangal.core.utils import extract_json_object


def test_plain_object():
    assert extract_json_object('{"decision": "APPROVE"}') == {"decision": "APPROVE"}


def test_whitespace_padding():
    assert extract_json_object('\n  {"a": 1}\n ') == {"a": 1}


def test_json_code_fence():
    text = 'Here is the result:\n```json\n{"a": 1, "b": [2, 3]}\n```\nDone.'
    assert extract_json_object(text) == {"a": 1, "b": [2, 3]}


def test_bare_code_fence():
    assert extract_json_object("```\n{\"x\": true}\n```") == {"x": True}


def test_prose_wrapped_object():
    text = 'I reviewed it. {"decision": "REQUEST_CHANGES"} -- log line after'
    assert extract_json_object(text) == {"decision": "REQUEST_CHANGES"}


def test_nested_and_trailing_logs():
    text = 'prefix {"outer": {"inner": 2}} 2026-01-01 12:00 done'
    assert extract_json_object(text) == {"outer": {"inner": 2}}


def test_braces_inside_strings_dont_confuse_balancer():
    text = '{"note": "use {curly} braces"}'
    assert extract_json_object(text) == {"note": "use {curly} braces"}


def test_no_json_returns_none():
    assert extract_json_object("no json here at all") is None


def test_empty_returns_none():
    assert extract_json_object("") is None


def test_array_root_returns_none():
    # Only objects are recovered; a bare array is not a dict.
    assert extract_json_object("[1, 2, 3]") is None
