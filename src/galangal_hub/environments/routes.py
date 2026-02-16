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

from fastapi import APIRouter, BackgroundTasks, HTTPException

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
    CredentialProfile,
    CredentialProfileCreate,
    CredentialProfileUpdate,
    Environment,
    EnvironmentCreate,
    EnvironmentStatus,
    EnvironmentUpdate,
    EnvironmentWithAgent,
    EnvFileWrite,
    GitStatus,
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

    # Allocate local path
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


# --- Agent Lifecycle ---


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

    # Get credentials if a profile is set
    agent_env_vars: dict[str, str] = {}
    if env.credential_profile_id:
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


# --- Helpers ---


async def _notify_env_status(env_id: str, status: str) -> None:
    """Send environment status update to connected dashboards."""
    try:
        from galangal_hub.server import _dashboard_connections

        import json

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
