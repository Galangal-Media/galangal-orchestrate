"""
Database CRUD operations for environments and credential profiles.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from galangal_hub.environments.models import (
    AIProvider,
    CredentialProfile,
    CredentialProfileCreate,
    CredentialProfileUpdate,
    Environment,
    EnvironmentCreate,
    EnvironmentStatus,
    EnvironmentUpdate,
    StartMode,
    VaultConfig,
)


async def create_environment_tables(db: aiosqlite.Connection) -> None:
    """Create environment-related tables if they don't exist."""
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS credential_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            credentials TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS environments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            repo_url TEXT NOT NULL,
            branch TEXT NOT NULL DEFAULT 'main',
            local_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'stopped',
            provider TEXT NOT NULL DEFAULT 'claude',
            credential_profile_id TEXT,
            env_vars TEXT NOT NULL DEFAULT '{}',
            env_files TEXT NOT NULL DEFAULT '{}',
            start_mode TEXT NOT NULL DEFAULT 'docker_compose',
            start_command TEXT,
            stop_command TEXT,
            docker_compose_file TEXT,
            ports TEXT NOT NULL DEFAULT '[]',
            vault TEXT NOT NULL DEFAULT '{}',
            agent_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (credential_profile_id) REFERENCES credential_profiles (id)
        );

        CREATE INDEX IF NOT EXISTS idx_environments_status ON environments (status);
        CREATE INDEX IF NOT EXISTS idx_environments_name ON environments (name);
        """
    )

    # Migration: add vault column to existing databases
    try:
        await db.execute("ALTER TABLE environments ADD COLUMN vault TEXT NOT NULL DEFAULT '{}'")
        await db.commit()
    except Exception:
        pass  # Column already exists

    # Migration: add stop_command column to existing databases
    try:
        await db.execute("ALTER TABLE environments ADD COLUMN stop_command TEXT")
        await db.commit()
    except Exception:
        pass  # Column already exists

    # Migration: rename doppler -> vault for databases from earlier schema
    try:
        await db.execute("ALTER TABLE environments RENAME COLUMN doppler TO vault")
        await db.commit()
    except Exception:
        pass  # Column doesn't exist or already renamed

    # Migration: add editor_port column to existing databases
    try:
        await db.execute("ALTER TABLE environments ADD COLUMN editor_port INTEGER")
        await db.commit()
    except Exception:
        pass  # Column already exists


class EnvironmentStorage:
    """CRUD operations for environments and credential profiles."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # --- Credential Profiles ---

    async def create_credential_profile(
        self, data: CredentialProfileCreate, encrypted_credentials: str
    ) -> CredentialProfile:
        """Create a new credential profile with pre-encrypted credentials."""
        now = datetime.now(timezone.utc).isoformat()
        profile_id = str(uuid.uuid4())

        await self._db.execute(
            """
            INSERT INTO credential_profiles (id, name, provider, credentials, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (profile_id, data.name, data.provider.value, encrypted_credentials, now, now),
        )
        await self._db.commit()

        return CredentialProfile(
            id=profile_id,
            name=data.name,
            provider=data.provider,
            credentials=data.credentials,
            created_at=now,
            updated_at=now,
        )

    async def list_credential_profiles(self) -> list[dict[str, Any]]:
        """List all credential profiles (raw rows)."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_profiles ORDER BY name ASC"
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def get_credential_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Get a credential profile by ID."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_profiles WHERE id = ?", (profile_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    async def get_credential_profile_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a credential profile by name."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_profiles WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    async def update_credential_profile(
        self,
        profile_id: str,
        data: CredentialProfileUpdate,
        encrypted_credentials: str | None = None,
    ) -> bool:
        """Update a credential profile. Returns True if found and updated."""
        now = datetime.now(timezone.utc).isoformat()
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [now]

        if data.name is not None:
            sets.append("name = ?")
            params.append(data.name)
        if data.provider is not None:
            sets.append("provider = ?")
            params.append(data.provider.value)
        if encrypted_credentials is not None:
            sets.append("credentials = ?")
            params.append(encrypted_credentials)

        params.append(profile_id)
        cursor = await self._db.execute(
            f"UPDATE credential_profiles SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_credential_profile(self, profile_id: str) -> bool:
        """Delete a credential profile. Returns True if deleted."""
        cursor = await self._db.execute(
            "DELETE FROM credential_profiles WHERE id = ?", (profile_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def is_credential_profile_in_use(self, profile_id: str) -> bool:
        """Check if a credential profile is referenced by any environment."""
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM environments WHERE credential_profile_id = ?",
            (profile_id,),
        )
        row = await cursor.fetchone()
        return row is not None and row[0] > 0

    # --- Environments ---

    async def create_environment(
        self, data: EnvironmentCreate, local_path: str
    ) -> Environment:
        """Create a new environment record."""
        now = datetime.now(timezone.utc).isoformat()
        env_id = str(uuid.uuid4())

        vault_json = json.dumps(data.vault.model_dump() if data.vault else {})

        await self._db.execute(
            """
            INSERT INTO environments (
                id, name, repo_url, branch, local_path, status, provider,
                credential_profile_id, env_vars, env_files, start_mode,
                start_command, stop_command, docker_compose_file, ports, vault,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                env_id,
                data.name,
                data.repo_url,
                data.branch,
                local_path,
                EnvironmentStatus.CLONING.value,
                data.provider.value,
                data.credential_profile_id,
                json.dumps(data.env_vars),
                json.dumps(data.env_files),
                data.start_mode.value,
                data.start_command,
                data.stop_command,
                data.docker_compose_file,
                json.dumps(data.ports),
                vault_json,
                now,
                now,
            ),
        )
        await self._db.commit()

        return Environment(
            id=env_id,
            name=data.name,
            repo_url=data.repo_url,
            branch=data.branch,
            local_path=local_path,
            status=EnvironmentStatus.CLONING,
            provider=data.provider,
            credential_profile_id=data.credential_profile_id,
            env_vars=data.env_vars,
            env_files=data.env_files,
            start_mode=data.start_mode,
            start_command=data.start_command,
            stop_command=data.stop_command,
            docker_compose_file=data.docker_compose_file,
            ports=data.ports,
            vault=data.vault,
            created_at=now,
            updated_at=now,
        )

    async def list_environments(self) -> list[Environment]:
        """List all environments."""
        cursor = await self._db.execute(
            "SELECT * FROM environments ORDER BY name ASC"
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_environment(dict(zip(columns, row))) for row in rows]

    async def get_environment(self, env_id: str) -> Environment | None:
        """Get an environment by ID."""
        cursor = await self._db.execute(
            "SELECT * FROM environments WHERE id = ?", (env_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return _row_to_environment(dict(zip(columns, row)))

    async def get_environment_by_name(self, name: str) -> Environment | None:
        """Get an environment by name."""
        cursor = await self._db.execute(
            "SELECT * FROM environments WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return _row_to_environment(dict(zip(columns, row)))

    async def update_environment(self, env_id: str, data: EnvironmentUpdate) -> bool:
        """Update environment config fields. Returns True if found and updated."""
        now = datetime.now(timezone.utc).isoformat()
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [now]

        if data.name is not None:
            sets.append("name = ?")
            params.append(data.name)
        if data.branch is not None:
            sets.append("branch = ?")
            params.append(data.branch)
        if data.provider is not None:
            sets.append("provider = ?")
            params.append(data.provider.value)
        if data.credential_profile_id is not None:
            sets.append("credential_profile_id = ?")
            params.append(data.credential_profile_id)
        if data.env_vars is not None:
            sets.append("env_vars = ?")
            params.append(json.dumps(data.env_vars))
        if data.env_files is not None:
            sets.append("env_files = ?")
            params.append(json.dumps(data.env_files))
        if data.start_mode is not None:
            sets.append("start_mode = ?")
            params.append(data.start_mode.value)
        if data.start_command is not None:
            sets.append("start_command = ?")
            params.append(data.start_command)
        if data.stop_command is not None:
            sets.append("stop_command = ?")
            params.append(data.stop_command)
        if data.docker_compose_file is not None:
            sets.append("docker_compose_file = ?")
            params.append(data.docker_compose_file)
        if data.ports is not None:
            sets.append("ports = ?")
            params.append(json.dumps(data.ports))
        if data.vault is not None:
            sets.append("vault = ?")
            params.append(json.dumps(data.vault.model_dump()))

        params.append(env_id)
        cursor = await self._db.execute(
            f"UPDATE environments SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def update_environment_status(
        self,
        env_id: str,
        status: EnvironmentStatus,
        error_message: str | None = None,
        agent_id: str | None = None,
    ) -> bool:
        """Update environment status and optionally error/agent fields."""
        now = datetime.now(timezone.utc).isoformat()
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, now]

        if error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        elif status != EnvironmentStatus.ERROR:
            # Clear error when transitioning to non-error state
            sets.append("error_message = NULL")

        if agent_id is not None:
            sets.append("agent_id = ?")
            params.append(agent_id)

        params.append(env_id)
        cursor = await self._db.execute(
            f"UPDATE environments SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def update_editor_port(self, env_id: str, port: int | None) -> bool:
        """Update the editor_port for an environment."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "UPDATE environments SET editor_port = ?, updated_at = ? WHERE id = ?",
            (port, now, env_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def clear_environment_agent(self, env_id: str) -> bool:
        """Clear the agent_id for an environment."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "UPDATE environments SET agent_id = NULL, updated_at = ? WHERE id = ?",
            (now, env_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_environment(self, env_id: str) -> bool:
        """Delete an environment record. Returns True if deleted."""
        cursor = await self._db.execute(
            "DELETE FROM environments WHERE id = ?", (env_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_environments_by_status(
        self, status: EnvironmentStatus
    ) -> list[Environment]:
        """Get all environments with a given status."""
        cursor = await self._db.execute(
            "SELECT * FROM environments WHERE status = ? ORDER BY name ASC",
            (status.value,),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_environment(dict(zip(columns, row))) for row in rows]


def _row_to_environment(row: dict[str, Any]) -> Environment:
    """Convert a database row dict to an Environment model."""
    vault_raw = json.loads(row.get("vault") or "{}")
    vault = VaultConfig(**vault_raw) if vault_raw else None

    return Environment(
        id=row["id"],
        name=row["name"],
        repo_url=row["repo_url"],
        branch=row["branch"],
        local_path=row["local_path"],
        status=EnvironmentStatus(row["status"]),
        provider=AIProvider(row["provider"]),
        credential_profile_id=row.get("credential_profile_id"),
        env_vars=json.loads(row.get("env_vars") or "{}"),
        env_files=json.loads(row.get("env_files") or "{}"),
        start_mode=StartMode(row["start_mode"]),
        start_command=row.get("start_command"),
        stop_command=row.get("stop_command"),
        docker_compose_file=row.get("docker_compose_file"),
        ports=json.loads(row.get("ports") or "[]"),
        vault=vault,
        agent_id=row.get("agent_id"),
        editor_port=row.get("editor_port"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
