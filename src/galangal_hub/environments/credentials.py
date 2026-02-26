"""
Credential encryption and profile management.

Uses Fernet symmetric encryption for credentials at rest.
Key sourced from HUB_SECRET_KEY env var or auto-generated.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Get or initialize the Fernet instance."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.environ.get("HUB_SECRET_KEY")
    if not key:
        # Auto-generate and persist alongside the database in /data/
        db_path = os.environ.get("HUB_DB_PATH", "/data/hub.db")
        data_dir = Path(db_path).parent
        secret_path = data_dir / ".hub_secret"
        if secret_path.exists():
            key = secret_path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_text(key)
            logger.info(f"Generated new encryption key at {secret_path}")
    else:
        # If the key isn't valid Fernet format, derive one from it
        if len(key) != 44 or not key.endswith("="):
            # Derive a valid Fernet key from the arbitrary secret
            derived = hashlib.sha256(key.encode()).digest()
            key = base64.urlsafe_b64encode(derived).decode()

    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_credentials(credentials: dict[str, str]) -> str:
    """Encrypt a credentials dict to a string for storage."""
    f = _get_fernet()
    plaintext = json.dumps(credentials).encode()
    return f.encrypt(plaintext).decode()


def decrypt_credentials(encrypted: str) -> dict[str, str]:
    """Decrypt a stored credentials string back to a dict."""
    f = _get_fernet()
    plaintext = f.decrypt(encrypted.encode())
    return json.loads(plaintext)


def redact_credentials(credentials: dict[str, str]) -> dict[str, str]:
    """Return a copy of credentials with values redacted for display."""
    redacted = {}
    for k, v in credentials.items():
        if len(v) > 8:
            redacted[k] = v[:4] + "..." + v[-4:]
        elif len(v) > 3:
            redacted[k] = v[:2] + "..." + v[-1:]
        else:
            redacted[k] = "***"
    return redacted


def credentials_to_env_vars(
    provider: str, credentials: dict[str, str]
) -> dict[str, str]:
    """Convert provider credentials to environment variables for agent spawning."""
    env_vars: dict[str, str] = {}

    if provider == "claude":
        if "api_key" in credentials:
            env_vars["ANTHROPIC_API_KEY"] = credentials["api_key"]
        if "org_id" in credentials:
            env_vars["ANTHROPIC_ORG_ID"] = credentials["org_id"]
    elif provider == "openai":
        if "api_key" in credentials:
            env_vars["OPENAI_API_KEY"] = credentials["api_key"]
        if "org_id" in credentials:
            env_vars["OPENAI_ORG_ID"] = credentials["org_id"]
    elif provider == "gemini":
        if "api_key" in credentials:
            env_vars["GOOGLE_API_KEY"] = credentials["api_key"]
        if "project_id" in credentials:
            env_vars["GOOGLE_CLOUD_PROJECT"] = credentials["project_id"]

    return env_vars


def reset_fernet() -> None:
    """Reset the cached Fernet instance (for testing)."""
    global _fernet
    _fernet = None
