"""CLI parser/dispatch tests - guard against flag rot and handler mis-wiring."""

import pytest

from galangal.cli import build_parser

PARSER = build_parser()


@pytest.mark.parametrize(
    ("argv", "expected_func"),
    [
        (["init"], "_cmd_init"),
        (["init", "--quick"], "_cmd_init"),
        (["doctor"], "_cmd_doctor"),
        (["start", "do a thing"], "_cmd_start"),
        (["list"], "_cmd_list"),
        (["switch", "t"], "_cmd_switch"),
        (["resume"], "_cmd_resume"),
        (["pause"], "_cmd_pause"),
        (["status"], "_cmd_status"),
        (["reset"], "_cmd_reset"),
        (["complete"], "_cmd_complete"),
        (["run"], "_cmd_run"),
    ],
)
def test_subcommand_dispatch(argv, expected_func):
    args = PARSER.parse_args(argv)
    assert args.func.__name__ == expected_func


def test_start_flags_plumb_through():
    args = PARSER.parse_args(
        ["start", "fix it", "--type", "bugfix", "--name", "n", "--headless", "--skip-discovery"]
    )
    assert args.type == "bugfix"
    assert args.name == "n"
    assert args.headless is True
    assert args.skip_discovery is True


def test_start_type_accepts_names_and_numbers():
    for choice in ["feature", "bugfix", "refactor", "chore", "docs", "hotfix", "1", "6"]:
        args = PARSER.parse_args(["start", "x", "--type", choice])
        assert args.type == choice


def test_start_rejects_invalid_type():
    # Guards the docs/CLI mismatch: it's "bugfix", not "bug_fix".
    with pytest.raises(SystemExit):
        PARSER.parse_args(["start", "x", "--type", "bug_fix"])


def test_start_defaults():
    args = PARSER.parse_args(["start", "x"])
    assert args.type is None  # falls back to the interactive picker
    assert args.headless is False


def test_subcommand_required():
    with pytest.raises(SystemExit):
        PARSER.parse_args([])


def test_every_subparser_has_a_func():
    """Every registered top-level command resolves to a handler.

    A command either sets `func` directly or delegates to nested subcommands
    (which set `func` themselves); both forms are accepted.
    """
    import argparse

    subparsers_action = next(
        a for a in PARSER._actions if isinstance(a, argparse._SubParsersAction)
    )
    missing = []
    for name, sub in subparsers_action.choices.items():
        has_func = "func" in sub._defaults
        has_nested = any(isinstance(a, argparse._SubParsersAction) for a in sub._actions)
        if not has_func and not has_nested:
            missing.append(name)
    assert not missing, f"subcommands without a handler: {missing}"
