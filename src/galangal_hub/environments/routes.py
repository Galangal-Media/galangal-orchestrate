"""
FastAPI routes for environments and credential profiles.
"""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect

from galangal_hub.environments.credentials import (
    credentials_to_env_vars,
    decrypt_credentials,
    encrypt_credentials,
    redact_credentials,
)
from galangal_hub.environments.git_ops import (
    GitError,
    checkout_branch,
    clone_repo,
    get_branches,
    get_repo_status,
    pull_repo,
    reset_to_remote,
)
from galangal_hub.environments.models import (
    ClaudeAccount,
    ClaudeAccountCreate,
    ConfigUpdateRequest,
    CredentialProfile,
    CredentialProfileCreate,
    CredentialProfileUpdate,
    EnvFileWrite,
    Environment,
    EnvironmentCreate,
    EnvironmentStatus,
    EnvironmentUpdate,
    EnvironmentWithAgent,
    GitStatus,
    Profile,
    ProfileCreate,
    ProfileUpdate,
)
from galangal_hub.environments.process_manager import process_manager
from galangal_hub.environments.storage import EnvironmentStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["environments"])

# Will be set during app startup
_env_storage: EnvironmentStorage | None = None

SOURCE_DIR = os.environ.get("HUB_SOURCE_DIR", os.path.join(os.getcwd(), "environments"))


def set_env_storage(storage: EnvironmentStorage) -> None:
    """Set the environment storage instance (called during app initialization)."""
    global _env_storage
    _env_storage = storage


def _storage() -> EnvironmentStorage:
    if _env_storage is None:
        raise HTTPException(status_code=503, detail="Environment storage not initialized")
    return _env_storage


# ============================================================
# Credential Profile Routes
# ============================================================


@router.get("/credentials")
async def list_credentials() -> list[CredentialProfile]:
    """List all credential profiles with redacted keys."""
    rows = await _storage().list_credential_profiles()
    profiles = []
    for row in rows:
        try:
            creds = decrypt_credentials(row["credentials"])
            redacted = redact_credentials(creds)
        except Exception:
            redacted = {"error": "decryption failed"}
        profiles.append(
            CredentialProfile(
                id=row["id"],
                name=row["name"],
                provider=row["provider"],
                credentials=redacted,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    return profiles


@router.post("/credentials")
async def create_credential(data: CredentialProfileCreate) -> CredentialProfile:
    """Create a new credential profile."""
    # Check name uniqueness
    existing = await _storage().get_credential_profile_by_name(data.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Profile name '{data.name}' already exists")

    encrypted = encrypt_credentials(data.credentials)
    profile = await _storage().create_credential_profile(data, encrypted)
    # Return with redacted credentials
    profile.credentials = redact_credentials(data.credentials)
    return profile


@router.put("/credentials/{profile_id}")
async def update_credential(profile_id: str, data: CredentialProfileUpdate) -> dict:
    """Update a credential profile."""
    existing = await _storage().get_credential_profile(profile_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Credential profile not found")

    encrypted = None
    if data.credentials is not None:
        encrypted = encrypt_credentials(data.credentials)

    updated = await _storage().update_credential_profile(profile_id, data, encrypted)
    if not updated:
        raise HTTPException(status_code=404, detail="Credential profile not found")
    return {"status": "updated"}


@router.delete("/credentials/{profile_id}")
async def delete_credential(profile_id: str) -> dict:
    """Delete a credential profile (fails if in use)."""
    if await _storage().is_credential_profile_in_use(profile_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete: profile is used by one or more environments",
        )

    deleted = await _storage().delete_credential_profile(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential profile not found")
    return {"status": "deleted"}


@router.post("/credentials/{profile_id}/test")
async def test_credential(profile_id: str) -> dict:
    """Test if credentials are valid (basic connectivity check)."""
    row = await _storage().get_credential_profile(profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="Credential profile not found")

    try:
        creds = decrypt_credentials(row["credentials"])
    except Exception:
        return {"valid": False, "error": "Failed to decrypt credentials"}

    # Basic validation — just check the key is non-empty
    provider = row["provider"]
    if provider == "claude":
        valid = bool(creds.get("api_key", "").startswith("sk-"))
    elif provider == "openai":
        valid = bool(creds.get("api_key", "").startswith("sk-"))
    elif provider == "gemini":
        valid = bool(creds.get("api_key"))
    else:
        valid = bool(creds)

    return {"valid": valid, "provider": provider}


# ============================================================
# Claude Account Routes
# ============================================================


def _account_config_dir(account_id: str) -> Path:
    """Get the isolated config directory for a Claude Max account."""
    return Path(SOURCE_DIR) / "claude-accounts" / account_id


@router.get("/claude-accounts")
async def list_claude_accounts() -> list[ClaudeAccount]:
    """List all Claude Max accounts."""
    return await _storage().list_claude_accounts()


@router.post("/claude-accounts")
async def create_claude_account(data: ClaudeAccountCreate) -> ClaudeAccount:
    """Create a new Claude Max account."""
    existing = await _storage().get_claude_account_by_name(data.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Account name '{data.name}' already exists")

    account_id = __import__("uuid").uuid4().hex[:12]
    config_dir = _account_config_dir(account_id)
    config_dir.mkdir(parents=True, exist_ok=True)

    return await _storage().create_claude_account(data, str(config_dir))


@router.delete("/claude-accounts/{account_id}")
async def delete_claude_account(account_id: str) -> dict:
    """Delete a Claude Max account (fails if in use)."""
    if await _storage().is_claude_account_in_use(account_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete: account is used by one or more profiles",
        )

    row = await _storage().get_claude_account(account_id)
    if not row:
        raise HTTPException(status_code=404, detail="Claude account not found")

    # Remove config directory
    config_dir = Path(row["config_dir"])
    if config_dir.exists():
        shutil.rmtree(str(config_dir), ignore_errors=True)

    deleted = await _storage().delete_claude_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Claude account not found")
    return {"status": "deleted"}


@router.post("/claude-accounts/{account_id}/login")
async def login_claude_account(account_id: str) -> dict:
    """Start an interactive ``claude auth login`` session.

    The actual terminal interaction happens over the WebSocket at
    ``/ws/claude-accounts/{id}/terminal``.  This REST endpoint just
    validates the account exists (kept for backwards-compat / simple check).
    """
    row = await _storage().get_claude_account(account_id)
    if not row:
        raise HTTPException(status_code=404, detail="Claude account not found")
    return {"status": "ok"}


async def claude_account_terminal(websocket: WebSocket, account_id: str) -> None:
    """WebSocket endpoint: interactive bash shell for a Claude account.

    Spawns bash with ``CLAUDE_CONFIG_DIR`` pointing at the account's
    isolated config directory so the user can run ``claude auth login``,
    ``claude auth status``, etc. interactively via xterm.js.
    """
    import fcntl
    import pty as pty_mod
    import select as select_mod
    import struct
    import termios

    from galangal_hub.auth import verify_websocket_auth

    # This forks an interactive login shell on the host - it MUST be authenticated
    # before we accept the socket (API key for agents, session cookie for the UI).
    if not await verify_websocket_auth(
        dict(websocket.headers), dict(websocket.query_params), dict(websocket.cookies)
    ):
        await websocket.close(code=1008, reason="Authentication required")
        return

    await websocket.accept()

    row = await _storage().get_claude_account(account_id)
    if not row:
        await websocket.close(code=1008, reason="Account not found")
        return

    config_dir = Path(row["config_dir"])
    config_dir.mkdir(parents=True, exist_ok=True)
    provider = row.get("provider", "claude")

    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    env["TERM"] = "xterm-256color"

    # Set provider-specific config directory env vars
    if provider == "claude":
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    elif provider == "codex":
        env["CODEX_HOME"] = str(config_dir)
    elif provider == "gemini":
        env["GEMINI_HOME"] = str(config_dir)

    master_fd, slave_fd = pty_mod.openpty()

    # Set an initial window size on the PTY
    winsize = struct.pack("HHHH", 30, 120, 0, 0)
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    pid = os.fork()
    if pid == 0:
        # Child — become session leader, attach to slave PTY, exec bash
        os.close(master_fd)
        os.setsid()
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvpe("bash", ["bash", "--login"], env)
    else:
        os.close(slave_fd)
        loop = asyncio.get_event_loop()

        async def _pty_reader() -> None:
            """Read PTY output and send to WebSocket."""
            try:
                while True:
                    readable = await loop.run_in_executor(
                        None,
                        lambda: select_mod.select([master_fd], [], [], 0.5)[0],
                    )
                    if readable:
                        data = await loop.run_in_executor(
                            None, lambda: os.read(master_fd, 4096)
                        )
                        if not data:
                            break
                        await websocket.send_bytes(data)
                    else:
                        # Check if child is still alive
                        try:
                            result = os.waitpid(pid, os.WNOHANG)
                            if result[0] != 0:
                                break
                        except ChildProcessError:
                            break
            except (WebSocketDisconnect, Exception):
                pass

        reader_task = asyncio.create_task(_pty_reader())

        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                # Handle resize messages (JSON with cols/rows)
                text = msg.get("text")
                if text and text.startswith('{"resize"'):
                    try:
                        resize = json_mod.loads(text)["resize"]
                        winsize = struct.pack(
                            "HHHH", resize["rows"], resize["cols"], 0, 0
                        )
                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                        os.kill(pid, 28)  # SIGWINCH
                        continue
                    except Exception:
                        pass
                data = msg.get("bytes") or (text.encode() if text else b"")
                if data:
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            reader_task.cancel()
            try:
                os.kill(pid, 9)
            except (ProcessLookupError, OSError):
                pass
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass
            try:
                os.close(master_fd)
            except OSError:
                pass

            # Refresh auth status after terminal closes
            await _refresh_account_status(account_id, provider, str(config_dir))

            try:
                await websocket.close()
            except Exception:
                pass


@router.post("/claude-accounts/{account_id}/logout")
async def logout_claude_account(account_id: str) -> dict:
    """Logout from a Claude Max account."""
    row = await _storage().get_claude_account(account_id)
    if not row:
        raise HTTPException(status_code=404, detail="Claude account not found")

    config_dir = Path(row["config_dir"])
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)}

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "auth", "logout",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
    except FileNotFoundError:
        pass  # CLI not installed
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    # Update DB
    await _storage().update_claude_account(
        account_id, logged_in=False, email=None, subscription_type=None
    )
    return {"status": "logged_out"}


async def _refresh_account_status(
    account_id: str, provider: str, config_dir: str
) -> dict:
    """Check auth status for any CLI provider and update the DB."""
    env = {**os.environ}
    env.pop("CLAUDECODE", None)

    if provider == "claude":
        env["CLAUDE_CONFIG_DIR"] = config_dir
        cmd = ["claude", "auth", "status", "--json"]
    elif provider == "codex":
        # Codex CLI stores auth in ~/.codex/auth.json (ignores env overrides)
        codex_auth = Path.home() / ".codex" / "auth.json"
        if codex_auth.exists():
            try:
                data = json_mod.loads(codex_auth.read_text())
                tokens = data.get("tokens", {})
                email = None
                plan_type = "pro"
                # Extract email from JWT id_token payload (base64 middle segment)
                id_token = tokens.get("id_token", "")
                if id_token:
                    import base64
                    parts = id_token.split(".")
                    if len(parts) >= 2:
                        payload = parts[1] + "=" * (-len(parts[1]) % 4)
                        claims = json_mod.loads(base64.urlsafe_b64decode(payload))
                        email = claims.get("email")
                        auth_info = claims.get("https://api.openai.com/auth", {})
                        plan_type = auth_info.get("chatgpt_plan_type", "pro")
                has_tokens = bool(tokens.get("access_token"))
                if has_tokens:
                    await _storage().update_claude_account(
                        account_id, logged_in=True, email=email, subscription_type=plan_type
                    )
                    return {"logged_in": True, "email": email, "subscription_type": plan_type}
            except Exception:
                pass
        await _storage().update_claude_account(account_id, logged_in=False)
        return {"logged_in": False}
    elif provider == "gemini":
        # Gemini CLI stores auth in ~/.gemini/ (ignores env overrides)
        gemini_dir = Path.home() / ".gemini"
        accounts_file = gemini_dir / "google_accounts.json"
        creds_file = gemini_dir / "oauth_creds.json"
        if accounts_file.exists() and creds_file.exists():
            try:
                accounts = json_mod.loads(accounts_file.read_text())
                email = accounts.get("active")
                await _storage().update_claude_account(
                    account_id, logged_in=True, email=email, subscription_type="gemini"
                )
                return {"logged_in": True, "email": email, "subscription_type": "gemini"}
            except Exception:
                pass
        await _storage().update_claude_account(account_id, logged_in=False)
        return {"logged_in": False}
    else:
        return {"logged_in": False, "error": f"Unknown provider: {provider}"}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        data = json_mod.loads(stdout.decode())

        logged_in = data.get("loggedIn", False)
        await _storage().update_claude_account(
            account_id,
            email=data.get("email") or None,
            logged_in=logged_in,
            subscription_type=data.get("subscriptionType") or None,
        )
        return {
            "logged_in": logged_in,
            "email": data.get("email"),
            "subscription_type": data.get("subscriptionType"),
        }
    except FileNotFoundError:
        return {"logged_in": False, "error": f"{provider} CLI not found"}
    except asyncio.TimeoutError:
        return {"logged_in": False, "error": "Status check timed out"}
    except Exception as e:
        return {"logged_in": False, "error": str(e)}


@router.get("/claude-accounts/{account_id}/status")
async def get_claude_account_status(account_id: str) -> dict:
    """Poll auth status for a CLI subscription account."""
    row = await _storage().get_claude_account(account_id)
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")

    provider = row.get("provider", "claude")
    config_dir = row["config_dir"]
    result = await _refresh_account_status(account_id, provider, config_dir)
    result["account_name"] = row["name"]
    return result


# ============================================================
# Environment Routes
# ============================================================


@router.get("/environments")
async def list_environments() -> list[EnvironmentWithAgent]:
    """List all environments with status."""
    envs = await _storage().list_environments()
    from galangal_hub.connection import manager

    result = []
    for env in envs:
        agent_connected = False
        agent_name = None
        if env.agent_id:
            agent = manager.get_agent(env.agent_id)
            if agent:
                agent_connected = True
                agent_name = agent.agent.agent_name

        result.append(
            EnvironmentWithAgent(
                **env.model_dump(),
                agent_connected=agent_connected,
                agent_name=agent_name,
            )
        )
    return result


@router.post("/environments")
async def create_environment(
    data: EnvironmentCreate, background_tasks: BackgroundTasks
) -> Environment:
    """Create a new environment and start cloning."""
    # Validate name uniqueness
    existing = await _storage().get_environment_by_name(data.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Environment name '{data.name}' already exists")

    # Validate credential profile exists if specified
    if data.credential_profile_id:
        profile = await _storage().get_credential_profile(data.credential_profile_id)
        if not profile:
            raise HTTPException(status_code=400, detail="Credential profile not found")

    # Allocate local path. The name becomes a directory under SOURCE_DIR (and is
    # later rmtree'd on delete), so it must be a single safe path segment - reject
    # separators / traversal so it can't escape SOURCE_DIR.
    if (
        not data.name
        or "/" in data.name
        or "\\" in data.name
        or data.name in (".", "..")
        or data.name != Path(data.name).name
    ):
        raise HTTPException(status_code=400, detail="Invalid environment name")
    local_path = str(Path(SOURCE_DIR) / data.name)

    env = await _storage().create_environment(data, local_path)

    # Start async clone
    background_tasks.add_task(_clone_environment, env)

    return env


async def _clone_environment(env: Environment) -> None:
    """Background task to clone repository."""
    try:
        Path(env.local_path).parent.mkdir(parents=True, exist_ok=True)

        await clone_repo(
            repo_url=env.repo_url,
            local_path=env.local_path,
            branch=env.branch,
        )

        # Write initial env files if provided
        if env.env_files:
            for filename, content in env.env_files.items():
                filepath = Path(env.local_path) / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(content)

        await _storage().update_environment_status(env.id, EnvironmentStatus.READY)
        logger.info(f"Environment {env.name} cloned successfully")
        await _notify_env_status(env.id, "ready")

    except GitError as e:
        logger.error(f"Failed to clone environment {env.name}: {e}")
        await _storage().update_environment_status(
            env.id, EnvironmentStatus.ERROR, error_message=str(e)
        )
        await _notify_env_status(env.id, "error")
    except Exception as e:
        logger.exception(f"Unexpected error cloning environment {env.name}")
        await _storage().update_environment_status(
            env.id, EnvironmentStatus.ERROR, error_message=str(e)
        )
        await _notify_env_status(env.id, "error")


@router.get("/environments/{env_id}")
async def get_environment(env_id: str) -> EnvironmentWithAgent:
    """Get environment details."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    from galangal_hub.connection import manager

    agent_connected = False
    agent_name = None
    if env.agent_id:
        agent = manager.get_agent(env.agent_id)
        if agent:
            agent_connected = True
            agent_name = agent.agent.agent_name

    return EnvironmentWithAgent(
        **env.model_dump(),
        agent_connected=agent_connected,
        agent_name=agent_name,
    )


@router.put("/environments/{env_id}")
async def update_environment(env_id: str, data: EnvironmentUpdate) -> dict:
    """Update environment configuration."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    # Validate credential profile if being changed
    if data.credential_profile_id is not None and data.credential_profile_id != "":
        profile = await _storage().get_credential_profile(data.credential_profile_id)
        if not profile:
            raise HTTPException(status_code=400, detail="Credential profile not found")

    # If branch is changing, perform git checkout
    if data.branch is not None and data.branch != env.branch:
        local = Path(env.local_path)
        if not local.exists():
            raise HTTPException(status_code=400, detail="Environment directory does not exist")
        try:
            await checkout_branch(env.local_path, data.branch)
        except GitError as e:
            raise HTTPException(status_code=400, detail=f"Failed to checkout branch: {e}")

    updated = await _storage().update_environment(env_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Environment not found")

    await _notify_env_status(env_id, "updated")
    return {"status": "updated"}


@router.delete("/environments/{env_id}")
async def delete_environment(env_id: str) -> dict:
    """Stop everything, remove files, delete environment record."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    # Stop agent, editor, and dev server
    await process_manager.stop_agent(env_id)
    await process_manager.stop_editor(env_id)
    await process_manager.stop_dev_server(env)

    # Remove local files
    local = Path(env.local_path)
    if local.exists():
        shutil.rmtree(str(local), ignore_errors=True)

    await _storage().delete_environment(env_id)
    await _notify_env_status(env_id, "deleted")
    return {"status": "deleted"}


# --- Env File Management ---


@router.post("/environments/{env_id}/env-files")
async def write_env_files(env_id: str, data: EnvFileWrite) -> dict:
    """Write env files to the environment's repo directory."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    local = Path(env.local_path)
    if not local.exists():
        raise HTTPException(status_code=400, detail="Environment directory does not exist")

    written = []
    for filename, content in data.files.items():
        # Security: prevent path traversal
        safe_name = Path(filename).name
        filepath = local / safe_name
        filepath.write_text(content)
        written.append(safe_name)

    # Also update DB record
    from galangal_hub.environments.models import EnvironmentUpdate as EU

    current_files = dict(env.env_files)
    current_files.update(data.files)
    await _storage().update_environment(env_id, EU(env_files=current_files))

    return {"status": "written", "files": written}


@router.get("/environments/{env_id}/env-files")
async def read_env_files(env_id: str) -> dict:
    """Read env file contents from disk."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    local = Path(env.local_path)
    files = {}

    # Read files tracked in DB
    for filename in env.env_files:
        safe_name = Path(filename).name
        filepath = local / safe_name
        if filepath.exists():
            files[safe_name] = filepath.read_text()

    # Also check for common env files not tracked
    for common in [".env", ".env.local", ".env.development"]:
        filepath = local / common
        if filepath.exists() and common not in files:
            files[common] = filepath.read_text()

    return {"files": files}


# --- Dev Server Lifecycle ---


@router.post("/environments/{env_id}/start")
async def start_dev_server(env_id: str) -> dict:
    """Start the dev server for an environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    if env.status not in (EnvironmentStatus.READY, EnvironmentStatus.STOPPED, EnvironmentStatus.ERROR):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start from status '{env.status.value}'",
        )

    await _storage().update_environment_status(env_id, EnvironmentStatus.STARTING)
    await _notify_env_status(env_id, "starting")

    try:
        await process_manager.start_dev_server(env)
        await _storage().update_environment_status(env_id, EnvironmentStatus.RUNNING)
        await _notify_env_status(env_id, "running")
        return {"status": "started"}
    except Exception as e:
        await _storage().update_environment_status(
            env_id, EnvironmentStatus.ERROR, error_message=str(e)
        )
        await _notify_env_status(env_id, "error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/environments/{env_id}/stop")
async def stop_dev_server(env_id: str) -> dict:
    """Stop the dev server for an environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    await process_manager.stop_dev_server(env)
    await _storage().update_environment_status(env_id, EnvironmentStatus.STOPPED)
    await _notify_env_status(env_id, "stopped")
    return {"status": "stopped"}


@router.post("/environments/{env_id}/restart")
async def restart_dev_server(env_id: str) -> dict:
    """Restart the dev server."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    await _storage().update_environment_status(env_id, EnvironmentStatus.STARTING)
    await _notify_env_status(env_id, "starting")

    try:
        await process_manager.restart_dev_server(env)
        await _storage().update_environment_status(env_id, EnvironmentStatus.RUNNING)
        await _notify_env_status(env_id, "running")
        return {"status": "restarted"}
    except Exception as e:
        await _storage().update_environment_status(
            env_id, EnvironmentStatus.ERROR, error_message=str(e)
        )
        await _notify_env_status(env_id, "error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/environments/{env_id}/logs")
async def get_dev_server_logs(env_id: str, kind: str = "dev_server", limit: int = 200) -> dict:
    """Get recent logs from the dev server or agent process."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    lines = process_manager.get_logs(env_id, kind=kind, limit=limit)
    return {"lines": lines, "running": process_manager.is_running(env_id, kind=kind)}


# --- Git Operations ---


@router.get("/environments/{env_id}/git-status")
async def get_git_status(env_id: str) -> GitStatus:
    """Get git status for an environment's repo."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    local = Path(env.local_path)
    if not local.exists():
        raise HTTPException(status_code=400, detail="Environment directory does not exist")

    try:
        status = await get_repo_status(env.local_path)
        branches = await get_branches(env.local_path)
        return GitStatus(
            branch=status["branch"],
            clean=status["clean"],
            last_commit_hash=status["last_commit_hash"],
            last_commit_message=status["last_commit_message"],
            remote_branches=branches,
        )
    except GitError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/environments/{env_id}/git-pull")
async def pull_environment(env_id: str, strategy: str = "ff-only") -> dict:
    """Pull latest changes for an environment.

    strategy: "ff-only" (default), "rebase", or "merge".
    """
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    if strategy not in ("ff-only", "rebase", "merge"):
        raise HTTPException(status_code=400, detail=f"Invalid strategy: {strategy}")

    try:
        output = await pull_repo(env.local_path, strategy=strategy)
        return {"status": "pulled", "output": output}
    except GitError as e:
        # Detect divergence so the frontend can offer rebase/merge
        stderr = e.stderr.lower() if e.stderr else str(e).lower()
        is_diverged = "diverging" in stderr or "not possible to fast-forward" in stderr
        if is_diverged and strategy == "ff-only":
            raise HTTPException(
                status_code=409,
                detail="Branches have diverged. Pull with rebase or merge to reconcile.",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/environments/{env_id}/git-reset")
async def reset_environment(env_id: str) -> dict:
    """Hard reset the current branch to match the remote."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    try:
        output = await reset_to_remote(env.local_path)
        return {"status": "reset", "output": output}
    except GitError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Profile Routes
# ============================================================


@router.get("/profiles")
async def list_profiles() -> list[Profile]:
    """List all profiles."""
    return await _storage().list_profiles()


@router.post("/profiles")
async def create_profile(data: ProfileCreate) -> Profile:
    """Create a new profile."""
    # Validate mutual exclusion: can't have both API key and subscription for same provider
    for cred, acct, label in [
        (data.claude_credential_id, data.claude_account_id, "Claude"),
        (data.codex_credential_id, data.codex_account_id, "Codex"),
        (data.gemini_credential_id, data.gemini_account_id, "Gemini"),
    ]:
        if cred and acct:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot set both {label} API key and {label} subscription account",
            )

    # Validate credential IDs exist
    for cred_id, label in [
        (data.claude_credential_id, "Claude"),
        (data.codex_credential_id, "Codex"),
        (data.gemini_credential_id, "Gemini"),
    ]:
        if cred_id:
            row = await _storage().get_credential_profile(cred_id)
            if not row:
                raise HTTPException(status_code=400, detail=f"{label} credential not found")

    # Validate subscription accounts exist
    for acct_id, label in [
        (data.claude_account_id, "Claude"),
        (data.codex_account_id, "Codex"),
        (data.gemini_account_id, "Gemini"),
    ]:
        if acct_id:
            row = await _storage().get_claude_account(acct_id)
            if not row:
                raise HTTPException(status_code=400, detail=f"{label} subscription account not found")

    return await _storage().create_profile(data)


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str) -> Profile:
    """Get a profile by ID."""
    profile = await _storage().get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: str, data: ProfileUpdate) -> dict:
    """Update a profile."""
    existing = await _storage().get_profile(profile_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Validate mutual exclusion for each provider after update
    for cred_field, acct_field, label in [
        ("claude_credential_id", "claude_account_id", "Claude"),
        ("codex_credential_id", "codex_account_id", "Codex"),
        ("gemini_credential_id", "gemini_account_id", "Gemini"),
    ]:
        new_cred = getattr(data, cred_field)
        new_acct = getattr(data, acct_field)
        eff_cred = new_cred if new_cred is not None else getattr(existing, cred_field)
        eff_acct = new_acct if new_acct is not None else getattr(existing, acct_field)
        if eff_cred == "":
            eff_cred = None
        if eff_acct == "":
            eff_acct = None
        if eff_cred and eff_acct:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot set both {label} API key and {label} subscription account",
            )

    # Validate credential IDs
    for cred_id, label in [
        (data.claude_credential_id, "Claude"),
        (data.codex_credential_id, "Codex"),
        (data.gemini_credential_id, "Gemini"),
    ]:
        if cred_id:
            row = await _storage().get_credential_profile(cred_id)
            if not row:
                raise HTTPException(status_code=400, detail=f"{label} credential not found")

    # Validate subscription accounts exist
    for acct_id, label in [
        (data.claude_account_id, "Claude"),
        (data.codex_account_id, "Codex"),
        (data.gemini_account_id, "Gemini"),
    ]:
        if acct_id and acct_id != "":
            row = await _storage().get_claude_account(acct_id)
            if not row:
                raise HTTPException(status_code=400, detail=f"{label} subscription account not found")

    updated = await _storage().update_profile(profile_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "updated"}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict:
    """Delete a profile (fails if in use by environments)."""
    if await _storage().is_profile_in_use(profile_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete: profile is used by one or more environments",
        )

    deleted = await _storage().delete_profile(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "deleted"}


# --- Agent Lifecycle ---


async def _resolve_profile_env_vars(profile: Profile) -> dict[str, str]:
    """Resolve all credential env vars from a profile's linked credentials."""
    env_vars: dict[str, str] = {}

    # Claude: prefer Max account over API key
    if profile.claude_account_id:
        row = await _storage().get_claude_account(profile.claude_account_id)
        if row:
            env_vars["CLAUDE_CONFIG_DIR"] = row["config_dir"]
    elif profile.claude_credential_id:
        row = await _storage().get_credential_profile(profile.claude_credential_id)
        if row:
            try:
                creds = decrypt_credentials(row["credentials"])
                env_vars.update(credentials_to_env_vars("claude", creds))
            except Exception:
                logger.warning(f"Failed to decrypt credentials for profile {profile.name}, provider claude")

    # Codex: prefer subscription account over API key
    if profile.codex_account_id:
        row = await _storage().get_claude_account(profile.codex_account_id)
        if row:
            # Codex uses ~/.codex/ directly (no env override needed for single-account)
            pass
    elif profile.codex_credential_id:
        row = await _storage().get_credential_profile(profile.codex_credential_id)
        if row:
            try:
                creds = decrypt_credentials(row["credentials"])
                env_vars.update(credentials_to_env_vars("openai", creds))
            except Exception:
                logger.warning(f"Failed to decrypt credentials for profile {profile.name}, provider openai")

    # Gemini: prefer subscription account over API key
    if profile.gemini_account_id:
        row = await _storage().get_claude_account(profile.gemini_account_id)
        if row:
            # Gemini uses ~/.gemini/ directly (no env override needed for single-account)
            pass
    elif profile.gemini_credential_id:
        row = await _storage().get_credential_profile(profile.gemini_credential_id)
        if row:
            try:
                creds = decrypt_credentials(row["credentials"])
                env_vars.update(credentials_to_env_vars("gemini", creds))
            except Exception:
                logger.warning(f"Failed to decrypt credentials for profile {profile.name}, provider gemini")

    return env_vars


@router.post("/environments/{env_id}/agent/start")
async def start_agent(env_id: str) -> dict:
    """Start a local galangal agent for this environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    if env.status not in (
        EnvironmentStatus.READY,
        EnvironmentStatus.RUNNING,
        EnvironmentStatus.STOPPED,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start agent from status '{env.status.value}'",
        )

    # Get credentials - prefer profile_id, fall back to credential_profile_id
    agent_env_vars: dict[str, str] = {}
    if env.profile_id:
        profile = await _storage().get_profile(env.profile_id)
        if profile:
            agent_env_vars = await _resolve_profile_env_vars(profile)
    elif env.credential_profile_id:
        row = await _storage().get_credential_profile(env.credential_profile_id)
        if row:
            try:
                creds = decrypt_credentials(row["credentials"])
                agent_env_vars = credentials_to_env_vars(row["provider"], creds)
            except Exception:
                logger.warning(f"Failed to decrypt credentials for env {env.name}")

    # Determine hub URL — use localhost with the current port
    hub_url = os.environ.get("HUB_INTERNAL_URL", "ws://127.0.0.1:8080/ws/agent")

    # Add hub API key if configured
    from galangal_hub.auth import get_api_key

    api_key = get_api_key()
    if api_key:
        agent_env_vars["GALANGAL_HUB_API_KEY"] = api_key

    try:
        await process_manager.start_agent(env, hub_url, agent_env_vars)
        return {"status": "agent_started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/environments/{env_id}/agent/stop")
async def stop_agent(env_id: str) -> dict:
    """Stop the local agent for this environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    await process_manager.stop_agent(env_id)
    await _storage().clear_environment_agent(env_id)
    return {"status": "agent_stopped"}


# --- Editor Lifecycle ---


@router.get("/editor/available")
async def check_editor_available() -> dict:
    """Check if code-server is installed on the host."""
    return {"available": process_manager.is_editor_available()}


@router.post("/environments/{env_id}/editor/start")
async def start_editor(env_id: str) -> dict:
    """Start a code-server editor for this environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    if process_manager.is_running(env_id, "editor"):
        port = env.editor_port
        return {"status": "already_running", "port": port, "url": f"http://localhost:{port}"}

    if not process_manager.is_editor_available():
        raise HTTPException(
            status_code=400,
            detail="code-server is not installed. Install it with: curl -fsSL https://code-server.dev/install.sh | sh",
        )

    try:
        port = process_manager._allocate_editor_port()
        await process_manager.start_editor(env, port)
        await _storage().update_editor_port(env_id, port)
        return {"status": "started", "port": port, "url": f"http://localhost:{port}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/environments/{env_id}/editor/stop")
async def stop_editor(env_id: str) -> dict:
    """Stop the code-server editor for this environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    await process_manager.stop_editor(env_id)
    await _storage().update_editor_port(env_id, None)
    return {"status": "stopped"}


@router.get("/environments/{env_id}/editor/status")
async def get_editor_status(env_id: str) -> dict:
    """Get the editor status for this environment."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    running = process_manager.is_running(env_id, "editor")
    port = env.editor_port if running else None
    url = f"http://localhost:{port}" if port else None
    return {"running": running, "port": port, "url": url}


# --- Vault / Doppler Integration ---


@router.get("/doppler/status")
async def get_doppler_status(token: str | None = None) -> dict:
    """Validate a Doppler service token and return its scope.

    Pass ?token=dp.st.xxx to validate. Returns installed, authenticated,
    and the project+config the token is scoped to.
    """
    installed = False
    authenticated = False
    project: str | None = None
    config: str | None = None

    try:
        cmd = ["doppler", "me", "--json"]
        if token:
            cmd.extend(["--token", token])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        installed = True
        if proc.returncode == 0:
            authenticated = True
            # Parse project + config from the token scope
            try:
                data = json_mod.loads(stdout.decode())
                # `doppler me --json` returns workplace/project/config info
                project = data.get("workplace", {}).get("project") or data.get("project")
                config = data.get("workplace", {}).get("config") or data.get("config")
            except (json_mod.JSONDecodeError, KeyError):
                pass
    except FileNotFoundError:
        pass  # doppler not installed
    except asyncio.TimeoutError:
        installed = True  # installed but timed out
    except Exception:
        pass

    return {
        "installed": installed,
        "authenticated": authenticated,
        "project": project,
        "config": config,
    }


# ============================================================
# Config Editor Routes
# ============================================================


@router.get("/environments/{env_id}/config")
async def get_galangal_config(env_id: str) -> dict:
    """Read .galangal/config.yaml from the environment's repo."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    config_path = Path(env.local_path) / ".galangal" / "config.yaml"
    if not config_path.exists():
        return {"config": {}, "raw": "", "exists": False}

    try:
        import yaml

        raw = config_path.read_text()
        parsed = yaml.safe_load(raw) or {}
        return {"config": parsed, "raw": raw, "exists": True}
    except Exception as e:
        return {"config": {}, "raw": config_path.read_text() if config_path.exists() else "", "exists": True, "error": str(e)}


@router.put("/environments/{env_id}/config")
async def update_galangal_config(env_id: str, data: ConfigUpdateRequest) -> dict:
    """Write .galangal/config.yaml to the environment's repo."""
    env = await _storage().get_environment(env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")

    local = Path(env.local_path)
    if not local.exists():
        raise HTTPException(status_code=400, detail="Environment directory does not exist")

    config_dir = local / ".galangal"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    try:
        import yaml

        if data.raw is not None:
            # Validate YAML
            yaml.safe_load(data.raw)
            config_path.write_text(data.raw)
        elif data.config is not None:
            yaml_str = yaml.dump(data.config, default_flow_style=False, sort_keys=False)
            config_path.write_text(yaml_str)
        else:
            raise HTTPException(status_code=400, detail="Provide either 'config' or 'raw'")

        return {"status": "saved"}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Helpers ---


async def _notify_env_status(env_id: str, status: str) -> None:
    """Send environment status update to connected dashboards."""
    try:
        import json

        from galangal_hub.server import _dashboard_connections

        message = json.dumps({
            "type": "env_status",
            "env_id": env_id,
            "status": status,
        })

        disconnected = []
        for ws in _dashboard_connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            if ws in _dashboard_connections:
                _dashboard_connections.remove(ws)
    except Exception:
        pass  # Don't fail operations due to notification errors
