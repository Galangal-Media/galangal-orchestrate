"""
Pydantic models for hub-hosted development environments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AIProvider(str, Enum):
    """Supported AI provider backends."""

    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"


class EnvironmentStatus(str, Enum):
    """Status of a development environment."""

    STOPPED = "stopped"
    CLONING = "cloning"
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class StartMode(str, Enum):
    """How the dev server is started."""

    SHELL = "shell"
    DOCKER_COMPOSE = "docker_compose"


# --- Credential Profile Models ---


class CredentialProfileCreate(BaseModel):
    """Request to create a credential profile."""

    name: str
    provider: AIProvider
    credentials: dict[str, str]  # e.g. {"api_key": "sk-...", "org_id": "..."}


class CredentialProfileUpdate(BaseModel):
    """Request to update a credential profile."""

    name: str | None = None
    provider: AIProvider | None = None
    credentials: dict[str, str] | None = None


class CredentialProfile(BaseModel):
    """A stored credential profile (credentials redacted for API responses)."""

    id: str
    name: str
    provider: AIProvider
    credentials: dict[str, str]  # Redacted in API responses
    created_at: str
    updated_at: str


# --- Vault Config (third-party secret providers) ---


class VaultProvider(str, Enum):
    """Supported third-party vault providers."""

    DOPPLER = "doppler"


class DopplerSettings(BaseModel):
    """Doppler-specific vault settings.

    Uses a Doppler service token which is scoped to a single project + config.
    The token is set as DOPPLER_TOKEN env var so any `doppler run` calls in
    the repo's own startup scripts pick it up automatically.
    """

    token: str = ""  # Service token (dp.st.xxx), scoped to project+config


class VaultConfig(BaseModel):
    """Third-party vault configuration for secret injection."""

    enabled: bool = False
    provider: VaultProvider | None = None
    doppler: DopplerSettings | None = None


# --- Environment Models ---


class EnvironmentCreate(BaseModel):
    """Request to create an environment."""

    name: str
    repo_url: str
    branch: str = "main"
    provider: AIProvider = AIProvider.CLAUDE
    credential_profile_id: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    env_files: dict[str, str] = Field(default_factory=dict)  # filename -> content
    start_mode: StartMode = StartMode.DOCKER_COMPOSE
    start_command: str | None = None
    stop_command: str | None = None
    docker_compose_file: str | None = None
    ports: list[int] = Field(default_factory=list)
    vault: VaultConfig | None = None


class EnvironmentUpdate(BaseModel):
    """Request to update an environment."""

    name: str | None = None
    branch: str | None = None
    provider: AIProvider | None = None
    credential_profile_id: str | None = None
    env_vars: dict[str, str] | None = None
    env_files: dict[str, str] | None = None
    start_mode: StartMode | None = None
    start_command: str | None = None
    stop_command: str | None = None
    docker_compose_file: str | None = None
    ports: list[int] | None = None
    vault: VaultConfig | None = None


class Environment(BaseModel):
    """A development environment."""

    id: str
    name: str
    repo_url: str
    branch: str
    local_path: str
    status: EnvironmentStatus
    provider: AIProvider
    credential_profile_id: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    env_files: dict[str, str] = Field(default_factory=dict)
    start_mode: StartMode
    start_command: str | None = None
    stop_command: str | None = None
    docker_compose_file: str | None = None
    ports: list[int] = Field(default_factory=list)
    vault: VaultConfig | None = None
    agent_id: str | None = None
    editor_port: int | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class EnvironmentWithAgent(Environment):
    """Environment with linked agent connection info."""

    agent_connected: bool = False
    agent_name: str | None = None


class EnvFileWrite(BaseModel):
    """Request to write env files to an environment."""

    files: dict[str, str]  # filename -> content


class GitStatus(BaseModel):
    """Git repository status."""

    branch: str
    clean: bool
    last_commit_hash: str
    last_commit_message: str
    remote_branches: list[str] = Field(default_factory=list)
