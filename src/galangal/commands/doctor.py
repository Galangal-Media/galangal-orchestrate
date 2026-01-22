"""
Doctor command - verify environment setup.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from galangal import __version__
from galangal.config.loader import get_project_root, is_initialized
from galangal.ui.console import console


def _check_mark(passed: bool) -> str:
    """Return check mark or X based on status."""
    return "[#b8bb26]✓[/]" if passed else "[#fb4934]✗[/]"


def _warn_mark() -> str:
    """Return warning mark."""
    return "[#fabd2f]⚠[/]"


def _run_command(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()
    except FileNotFoundError:
        return False, "Command not found"
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def check_python_version() -> tuple[bool, str]:
    """Check Python version is 3.10+."""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    passed = version.major == 3 and version.minor >= 10
    return passed, version_str


def check_claude_cli() -> tuple[bool, str]:
    """Check Claude CLI is installed."""
    path = shutil.which("claude")
    if not path:
        return False, "Not found in PATH"

    # Try to get version
    success, output = _run_command(["claude", "--version"])
    if success and output:
        # Extract version from output
        return True, output.split("\n")[0]
    return True, "Installed"


def check_claude_auth() -> tuple[bool, str]:
    """Check Claude CLI is authenticated."""
    # Try a simple command that requires auth
    success, output = _run_command(["claude", "--version"])
    if not success:
        return False, "Could not verify"

    # The version command works without auth, so we just check if claude exists
    # A more thorough check would require actually invoking claude
    return True, "CLI available (run 'claude' to verify auth)"


def check_git_installed() -> tuple[bool, str]:
    """Check git is installed."""
    path = shutil.which("git")
    if not path:
        return False, "Not found in PATH"

    success, output = _run_command(["git", "--version"])
    if success:
        return True, output.replace("git version ", "")
    return False, "Could not get version"


def check_git_config() -> tuple[bool, str]:
    """Check git is configured with user info."""
    name_ok, name = _run_command(["git", "config", "user.name"])
    email_ok, email = _run_command(["git", "config", "user.email"])

    if name_ok and email_ok and name and email:
        return True, f"{name} <{email}>"
    elif name_ok and name:
        return False, f"user.name set ({name}), but user.email missing"
    elif email_ok and email:
        return False, f"user.email set ({email}), but user.name missing"
    return False, "user.name and user.email not configured"


def check_github_cli() -> tuple[bool | None, str]:
    """Check GitHub CLI is available (optional)."""
    path = shutil.which("gh")
    if not path:
        return None, "Not installed (optional)"

    success, output = _run_command(["gh", "--version"])
    if success:
        version = output.split("\n")[0] if output else "Installed"
        # Check auth status
        auth_ok, _ = _run_command(["gh", "auth", "status"])
        if auth_ok:
            return True, f"{version} (authenticated)"
        return True, f"{version} (not authenticated - run 'gh auth login')"
    return None, "Could not get version"


def check_config_valid() -> tuple[bool | None, str]:
    """Check galangal config is valid."""
    if not is_initialized():
        return None, "Not initialized (run 'galangal init')"

    try:
        from galangal.config.loader import load_config
        from galangal.config.loader import reset_caches

        reset_caches()  # Ensure fresh load
        config = load_config()
        return True, f"Valid ({config.project.name})"
    except Exception as e:
        return False, f"Invalid: {e}"


def check_tasks_dir() -> tuple[bool | None, str]:
    """Check tasks directory is writable."""
    if not is_initialized():
        return None, "Not initialized"

    try:
        from galangal.config.loader import get_tasks_dir

        tasks_dir = get_tasks_dir()
        if tasks_dir.exists():
            # Check writable
            test_file = tasks_dir / ".write_test"
            try:
                test_file.touch()
                test_file.unlink()
                return True, f"Writable ({tasks_dir.name}/)"
            except OSError:
                return False, f"Not writable ({tasks_dir})"
        else:
            # Directory doesn't exist yet, check parent is writable
            parent = tasks_dir.parent
            if parent.exists():
                return True, f"Will be created ({tasks_dir.name}/)"
            return False, f"Parent directory doesn't exist"
    except Exception as e:
        return False, str(e)


def check_mistake_tracking() -> tuple[bool | None, str]:
    """Check if mistake tracking dependencies are available."""
    try:
        import sentence_transformers  # noqa: F401
        import sqlite_vss  # noqa: F401

        return True, "Available (sentence-transformers + sqlite-vss)"
    except ImportError:
        return None, "Not installed (pip install galangal-orchestrate[full])"


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run environment checks and report status."""
    console.print(f"\n[bold #fe8019]Galangal Doctor[/] [#7c6f64]v{__version__}[/]\n")

    all_passed = True
    warnings = 0

    checks = [
        ("Python 3.10+", check_python_version),
        ("Git installed", check_git_installed),
        ("Git configured", check_git_config),
        ("Claude CLI", check_claude_cli),
        ("GitHub CLI", check_github_cli),
        ("Config file", check_config_valid),
        ("Tasks directory", check_tasks_dir),
        ("Mistake tracking", check_mistake_tracking),
    ]

    for name, check_func in checks:
        try:
            result, detail = check_func()
        except Exception as e:
            result, detail = False, str(e)

        if result is True:
            mark = _check_mark(True)
        elif result is False:
            mark = _check_mark(False)
            all_passed = False
        else:  # None = optional/warning
            mark = _warn_mark()
            warnings += 1

        console.print(f"  {mark} {name}: [#a89984]{detail}[/]")

    console.print()

    if all_passed and warnings == 0:
        console.print("[#b8bb26]All checks passed![/]\n")
        return 0
    elif all_passed:
        console.print(f"[#fabd2f]All required checks passed ({warnings} optional warnings)[/]\n")
        return 0
    else:
        console.print("[#fb4934]Some checks failed. Please fix the issues above.[/]\n")
        return 1
