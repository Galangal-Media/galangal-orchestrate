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
        # Auto-generate and persist alongside the database. This is a fallback:
        # the key sits next to the ciphertext, so at-rest encryption only protects
        # against casual access. Set HUB_SECRET_KEY (kept outside the data dir /
        # in a secrets manager) for real protection.
        db_path = os.environ.get("HUB_DB_PATH", "/data/hub.db")
        data_dir = Path(db_path).parent
        secret_path = data_dir / ".hub_secret"
        if secret_path.exists():
            key = secret_path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            # Write 0600 so other users on the host can't read the key.
            secret_path.touch(mode=0o600, exist_ok=True)
            secret_path.write_text(key)
            try:
                secret_path.chmod(0o600)
            except OSError:
                pass
            logger.warning(
                "HUB_SECRET_KEY not set; generated a key at %s (stored next to the "
                "database). Set HUB_SECRET_KEY for real at-rest protection.",
                secret_path,
            )
    else:
        # If the key isn't valid Fernet format, derive one from the arbitrary
        # secret with a slow KDF (scrypt) rather than a single SHA-256 round.
        if len(key) != 44 or not key.endswith("="):
            derived = hashlib.scrypt(
                key.encode(), salt=b"galangal-hub-credkey-v1", n=16384, r=8, p=1, dklen=32
            )
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
        # Only ever reveal the last 4 chars, and only for values long enough that
        # those 4 chars are a small fraction of the secret. Never show a prefix.
        redacted[k] = ("..." + v[-4:]) if len(v) >= 12 else "***"
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
