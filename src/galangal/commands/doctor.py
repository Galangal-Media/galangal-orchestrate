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


def check_active_model() -> tuple[bool | None, str]:
    """Report which model the default backend will use.

    A blank model means the CLI's own default model is used, so galangal
    automatically picks up whatever model the installed CLI defaults to.
    """
    if not is_initialized():
        return None, "Not initialized (uses CLI default model)"

    try:
        from galangal.config.loader import load_config, reset_caches

        reset_caches()  # Ensure fresh load
        config = load_config()
    except Exception as e:
        return False, f"Could not read config: {e}"

    default_name = config.ai.default
    backend = config.ai.backends.get(default_name)
    model = backend.model if backend else None
    base = f"{default_name}: {model}" if model else f"{default_name}: CLI default model"

    overrides = config.ai.stage_models
    if overrides:
        pairs = ", ".join(f"{stage}={mdl}" for stage, mdl in sorted(overrides.items()))
        return True, f"{base} (per-stage: {pairs})"
    return True, base


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


def _is_legacy_codex_args(args: list[str]) -> bool:
    """Return True if args look like legacy read-only structured output mode."""
    legacy_markers = ("--output-schema", "{schema_file}", "{output_file}")
    for arg in args:
        if arg in legacy_markers:
            return True
        if "schema_file" in arg or "output_file" in arg:
            return True
    return False


def check_codex_backend_mode() -> tuple[bool | None, str]:
    """
    Check whether Codex backend is configured for editable mode.

    Returns:
        - True: Codex is editable (or not configured)
        - None: Legacy read-only config detected (warning)
        - False: Unexpected check failure
    """
    if not is_initialized():
        return None, "Not initialized"

    try:
        from galangal.config.loader import load_config, reset_caches

        reset_caches()  # Ensure fresh load
        config = load_config()
    except Exception as e:
        return False, f"Could not read config: {e}"

    codex = config.ai.backends.get("codex")
    if codex is None:
        return True, "Not configured"

    legacy_reasons: list[str] = []
    if codex.read_only:
        legacy_reasons.append("read_only=true")
    if _is_legacy_codex_args(codex.args):
        legacy_reasons.append("output-schema args")

    if legacy_reasons:
        reasons = ", ".join(legacy_reasons)
        return None, f"Legacy read-only config detected ({reasons})"

    return True, "Editable mode (can modify files)"


def _extract_flag_value(args: list[str], flag: str) -> str | None:
    """Extract CLI flag value from `--flag value` or `--flag=value` forms."""
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return None


def check_gemini_backend_mode() -> tuple[bool | None, str]:
    """
    Check whether Gemini backend is configured for headless editable mode.

    Returns:
        - True: Gemini config is edit-capable for headless runs
        - None: Legacy/non-headless config detected (warning)
        - False: Unexpected check failure
    """
    if not is_initialized():
        return None, "Not initialized"

    try:
        from galangal.config.loader import load_config, reset_caches

        reset_caches()  # Ensure fresh load
        config = load_config()
    except Exception as e:
        return False, f"Could not read config: {e}"

    gemini = config.ai.backends.get("gemini")
    if gemini is None:
        return True, "Using backend defaults (headless editable mode)"

    args = gemini.args
    warnings: list[str] = []

    if gemini.read_only:
        warnings.append("read_only=true")

    # Gemini CLI defaults to interactive mode unless --prompt/-p is provided.
    has_prompt_flag = any(a in ("--prompt", "-p") for a in args) or any(
        a.startswith("--prompt=") or a.startswith("-p=") for a in args
    )
    if not has_prompt_flag:
        warnings.append("missing --prompt/-p (interactive mode)")

    # For editing in headless mode, approvals must be auto-accepted.
    approval_mode = _extract_flag_value(args, "--approval-mode")
    has_yolo = any(a in ("-y", "--yolo") for a in args)
    if not has_yolo and approval_mode not in {"yolo", "auto_edit"}:
        warnings.append("missing auto approval (use --approval-mode yolo or auto_edit)")

    # Legacy/invalid args from older implementation.
    if "--max-tokens" in args:
        warnings.append("legacy --max-tokens arg")

    if warnings:
        return None, f"Legacy/non-editable config detected ({', '.join(warnings)})"

    return True, "Headless editable mode"


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run environment checks and report status."""
    console.print(f"\n[bold #fe8019]Galangal Doctor[/] [#7c6f64]v{__version__}[/]\n")

    all_passed = True
    warnings = 0
    codex_legacy_warning = False
    gemini_legacy_warning = False

    checks = [
        ("Python 3.10+", check_python_version),
        ("Git installed", check_git_installed),
        ("Git configured", check_git_config),
        ("Claude CLI", check_claude_cli),
        ("GitHub CLI", check_github_cli),
        ("Config file", check_config_valid),
        ("Active model", check_active_model),
        ("Codex backend mode", check_codex_backend_mode),
        ("Gemini backend mode", check_gemini_backend_mode),
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
            if name == "Codex backend mode" and "legacy read-only config" in detail.lower():
                codex_legacy_warning = True
            if name == "Gemini backend mode" and "legacy/non-editable config" in detail.lower():
                gemini_legacy_warning = True

        console.print(f"  {mark} {name}: [#a89984]{detail}[/]")

    if codex_legacy_warning:
        console.print("\n[#fabd2f]Codex is in legacy read-only mode.[/]")
        console.print(
            "[#a89984]Update .galangal/config.yaml so Codex can edit code in headless runs:[/]"
        )
        console.print(
            """\n[dim]ai:
  backends:
    codex:
      command: codex
      args: ["exec", "--full-auto"]
      read_only: false[/]\n"""
        )

    if gemini_legacy_warning:
        console.print("\n[#fabd2f]Gemini is in legacy/non-editable mode.[/]")
        console.print(
            "[#a89984]Update .galangal/config.yaml so Gemini runs headless and can edit code:[/]"
        )
        console.print(
            """\n[dim]ai:
  backends:
    gemini:
      command: gemini
      args: ["--approval-mode", "yolo", "--prompt", "", "--output-format", "stream-json"]
      read_only: false[/]\n"""
        )

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
