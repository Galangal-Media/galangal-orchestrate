"""CLI commands."""

from galangal.commands.approve import cmd_approve, cmd_approve_design
from galangal.commands.complete import cmd_complete
from galangal.commands.init import cmd_init
from galangal.commands.list import cmd_list
from galangal.commands.pause import cmd_pause
from galangal.commands.prompts import cmd_prompts
from galangal.commands.reset import cmd_reset
from galangal.commands.resume import cmd_resume
from galangal.commands.skip import (
    cmd_skip_benchmark,
    cmd_skip_contract,
    cmd_skip_design,
    cmd_skip_migration,
    cmd_skip_security,
    cmd_skip_to,
)
from galangal.commands.start import cmd_start
from galangal.commands.status import cmd_status
from galangal.commands.switch import cmd_switch

__all__ = [
    "cmd_init",
    "cmd_start",
    "cmd_resume",
    "cmd_status",
    "cmd_list",
    "cmd_switch",
    "cmd_pause",
    "cmd_approve",
    "cmd_approve_design",
    "cmd_skip_design",
    "cmd_skip_security",
    "cmd_skip_migration",
    "cmd_skip_contract",
    "cmd_skip_benchmark",
    "cmd_skip_to",
    "cmd_reset",
    "cmd_complete",
    "cmd_prompts",
]
