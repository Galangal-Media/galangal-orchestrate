"""
Process manager for dev servers and local AI agents.

Manages lifecycle of dev server processes (shell or docker compose)
and local galangal agent processes per environment.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import shutil
import signal
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from galangal_hub.environments.models import (
    Environment,
    EnvironmentStatus,
    StartMode,
    VaultProvider,
)

logger = logging.getLogger(__name__)


def _vault_env_vars(env: Environment) -> dict[str, str]:
    """Return extra environment variables for vault provider integration."""
    vault = env.vault
    if not vault or not vault.enabled or not vault.provider:
        return {}

    if vault.provider == VaultProvider.DOPPLER:
        doppler = vault.doppler
        if not doppler or not doppler.token:
            return {}
        # Setting DOPPLER_TOKEN lets any `doppler run` call in the repo's
        # startup scripts pick it up automatically — no command wrapping needed.
        return {"DOPPLER_TOKEN": doppler.token}

    return {}

LOG_BUFFER_SIZE = 500


@dataclass
class ManagedProcess:
    """A managed subprocess with log capture."""

    process: asyncio.subprocess.Process
    env_id: str
    kind: str  # "dev_server" or "agent"
    logs: collections.deque = field(default_factory=lambda: collections.deque(maxlen=LOG_BUFFER_SIZE))
    _read_task: asyncio.Task | None = field(default=None, repr=False)


class ProcessManager:
    """Singleton manager for dev server and agent processes."""

    def __init__(self) -> None:
        self._processes: dict[str, ManagedProcess] = {}  # key: "{env_id}:{kind}"
        self._on_status_change: list[Any] = []

    def _key(self, env_id: str, kind: str) -> str:
        return f"{env_id}:{kind}"

    def on_status_change(self, callback: Any) -> None:
        """Register a callback for environment status changes."""
        self._on_status_change.append(callback)

    async def _notify_status_change(self, env_id: str, status: str) -> None:
        """Notify listeners of status change."""
        for cb in self._on_status_change:
            try:
                await cb(env_id, status)
            except Exception:
                logger.exception("Error in status change callback")

    async def start_dev_server(self, env: Environment) -> None:
        """Start a dev server process for an environment."""
        key = self._key(env.id, "dev_server")
        if key in self._processes:
            mp = self._processes[key]
            if mp.process.returncode is None:
                logger.warning(f"Dev server already running for {env.name}")
                return

        # Build environment variables (vault secrets injected via env vars)
        merged_env = {**os.environ, **env.env_vars, **_vault_env_vars(env)}

        if env.start_mode == StartMode.DOCKER_COMPOSE:
            compose_file = env.docker_compose_file or "docker-compose.yml"
            cmd = ["docker", "compose", "-f", compose_file, "up"]
        elif env.start_mode == StartMode.SHELL:
            if not env.start_command:
                raise ValueError(f"No start_command configured for environment {env.name}")
            cmd = ["sh", "-c", env.start_command]
        else:
            raise ValueError(f"Unknown start mode: {env.start_mode}")

        logger.info(f"Starting dev server for {env.name}: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=env.local_path,
            env=merged_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        mp = ManagedProcess(process=proc, env_id=env.id, kind="dev_server")
        self._processes[key] = mp

        # Start background log reader
        mp._read_task = asyncio.create_task(self._read_output(mp))

    async def stop_dev_server(self, env: Environment) -> None:
        """Stop a dev server process.

        If a stop_command is configured, run it first (e.g. a cleanup script),
        then terminate the managed process.
        """
        key = self._key(env.id, "dev_server")

        # Run stop command if configured
        if env.stop_command:
            try:
                merged_env = {**os.environ, **env.env_vars, **_vault_env_vars(env)}
                logger.info(f"Running stop command for {env.name}: {env.stop_command}")
                proc = await asyncio.create_subprocess_exec(
                    "sh", "-c", env.stop_command,
                    cwd=env.local_path,
                    env=merged_env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=30)
                except asyncio.TimeoutError:
                    logger.warning(f"Stop command timed out for {env.name}, killing")
                    proc.kill()
            except Exception:
                logger.exception(f"Error running stop command for {env.name}")

        mp = self._processes.get(key)
        if not mp:
            return

        await self._terminate_process(mp)
        del self._processes[key]

    async def restart_dev_server(self, env: Environment) -> None:
        """Restart a dev server."""
        await self.stop_dev_server(env)
        await self.start_dev_server(env)

    async def start_agent(
        self,
        env: Environment,
        hub_internal_url: str,
        agent_env_vars: dict[str, str] | None = None,
    ) -> None:
        """Start a local galangal agent for an environment."""
        key = self._key(env.id, "agent")
        if key in self._processes:
            mp = self._processes[key]
            if mp.process.returncode is None:
                logger.warning(f"Agent already running for {env.name}")
                return

        # Build environment with AI credentials + vault secrets
        merged_env = {
            **os.environ,
            **env.env_vars,
            **(agent_env_vars or {}),
            **_vault_env_vars(env),
        }

        cmd = [
            "python", "-m", "galangal", "run",
            "--hub-url", hub_internal_url,
        ]

        logger.info(f"Starting agent for {env.name}: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=env.local_path,
            env=merged_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        mp = ManagedProcess(process=proc, env_id=env.id, kind="agent")
        self._processes[key] = mp
        mp._read_task = asyncio.create_task(self._read_output(mp))

    @staticmethod
    def is_editor_available() -> bool:
        """Check if code-server is installed and on PATH."""
        return shutil.which("code-server") is not None

    async def start_editor(self, env: Environment, port: int) -> None:
        """Start a code-server editor process for an environment."""
        if not self.is_editor_available():
            raise FileNotFoundError(
                "code-server is not installed. "
                "Install it with: curl -fsSL https://code-server.dev/install.sh | sh"
            )

        key = self._key(env.id, "editor")
        if key in self._processes:
            mp = self._processes[key]
            if mp.process.returncode is None:
                logger.warning(f"Editor already running for {env.name}")
                return

        cmd = [
            "code-server",
            "--port", str(port),
            "--auth", "none",
            "--host", "0.0.0.0",
            "--disable-telemetry",
            env.local_path,
        ]

        logger.info(f"Starting editor for {env.name} on port {port}: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=env.local_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        mp = ManagedProcess(process=proc, env_id=env.id, kind="editor")
        self._processes[key] = mp
        mp._read_task = asyncio.create_task(self._read_output(mp))

    async def stop_editor(self, env_id: str) -> None:
        """Stop an editor process."""
        key = self._key(env_id, "editor")
        mp = self._processes.get(key)
        if not mp:
            return

        await self._terminate_process(mp)
        del self._processes[key]

    def _allocate_editor_port(self) -> int:
        """Find a free port starting from base 13370."""
        base_port = 13370
        # Collect ports already in use by editors
        used_ports: set[int] = set()
        for key, mp in self._processes.items():
            if key.endswith(":editor") and mp.process.returncode is None:
                # Extract port from the process args if possible
                pass

        for port in range(base_port, base_port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("0.0.0.0", port))
                    return port
            except OSError:
                continue

        raise RuntimeError("No free port available for editor (tried 13370-13469)")

    async def stop_agent(self, env_id: str) -> None:
        """Stop an agent process."""
        key = self._key(env_id, "agent")
        mp = self._processes.get(key)
        if not mp:
            return

        await self._terminate_process(mp)
        del self._processes[key]

    async def stop_all(self) -> None:
        """Stop all managed processes. Called on hub shutdown."""
        keys = list(self._processes.keys())
        for key in keys:
            mp = self._processes.get(key)
            if mp:
                await self._terminate_process(mp)
        self._processes.clear()

    def get_logs(self, env_id: str, kind: str = "dev_server", limit: int = 200) -> list[str]:
        """Get recent log lines for an environment's process."""
        key = self._key(env_id, kind)
        mp = self._processes.get(key)
        if not mp:
            return []
        logs = list(mp.logs)
        return logs[-limit:]

    def is_running(self, env_id: str, kind: str = "dev_server") -> bool:
        """Check if a process is running."""
        key = self._key(env_id, kind)
        mp = self._processes.get(key)
        if not mp:
            return False
        return mp.process.returncode is None

    async def restore_on_startup(self, env_storage: Any) -> None:
        """
        Check environments marked as 'running' on startup.

        Since processes don't survive hub restart, mark them as 'stopped'.
        """
        from galangal_hub.environments.storage import EnvironmentStorage

        if not isinstance(env_storage, EnvironmentStorage):
            return

        running_envs = await env_storage.get_environments_by_status(
            EnvironmentStatus.RUNNING
        )
        starting_envs = await env_storage.get_environments_by_status(
            EnvironmentStatus.STARTING
        )

        for env in running_envs + starting_envs:
            logger.info(
                f"Environment {env.name} was {env.status.value} before restart, marking as ready"
            )
            await env_storage.update_environment_status(
                env.id, EnvironmentStatus.READY
            )
            await env_storage.clear_environment_agent(env.id)

        # Also clean up any stuck in cloning state
        cloning_envs = await env_storage.get_environments_by_status(
            EnvironmentStatus.CLONING
        )
        for env in cloning_envs:
            logger.info(
                f"Environment {env.name} was cloning before restart, marking as error"
            )
            await env_storage.update_environment_status(
                env.id,
                EnvironmentStatus.ERROR,
                error_message="Clone interrupted by hub restart",
            )

    async def _read_output(self, mp: ManagedProcess) -> None:
        """Read process stdout and append to log buffer."""
        try:
            while True:
                if mp.process.stdout is None:
                    break
                line = await mp.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").rstrip("\n")
                mp.logs.append(decoded)
        except Exception:
            logger.exception(f"Error reading output for {mp.env_id}:{mp.kind}")
        finally:
            # Process has exited
            rc = mp.process.returncode
            mp.logs.append(f"[Process exited with code {rc}]")
            await self._notify_status_change(mp.env_id, "exited")

    async def _terminate_process(self, mp: ManagedProcess) -> None:
        """Gracefully terminate a process."""
        if mp.process.returncode is not None:
            # Already dead
            if mp._read_task and not mp._read_task.done():
                mp._read_task.cancel()
            return

        logger.info(f"Terminating {mp.kind} for env {mp.env_id}")

        try:
            mp.process.terminate()
            try:
                await asyncio.wait_for(mp.process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning(f"Process didn't terminate, killing {mp.kind} for {mp.env_id}")
                mp.process.kill()
                await mp.process.wait()
        except ProcessLookupError:
            pass

        if mp._read_task and not mp._read_task.done():
            mp._read_task.cancel()
            try:
                await mp._read_task
            except asyncio.CancelledError:
                pass


# Global singleton
process_manager = ProcessManager()
