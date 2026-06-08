"""
Authentication for Galangal Hub.

Supports:
- API key authentication (for agents and API clients)
- Username/password authentication (for the dashboard, via signed session cookies)
- Tailscale authentication (trusting peer identity injected by Tailscale)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Optional API key for agent/API authentication
_api_key: str | None = None

# Dashboard credentials (password stored as "salt$scrypt-hash")
_username: str | None = None
_password_hash: str | None = None

# Secret used to sign session cookies. Random per-process by default; set a stable
# value (HUB_SECRET_KEY / HUB_SESSION_SECRET) to keep sessions valid across restarts.
_session_secret: str = secrets.token_hex(32)

# Session lifetime
SESSION_TTL_SECONDS = 7 * 24 * 3600

security = HTTPBearer(auto_error=False)

SESSION_COOKIE = "galangal_session"


# ---------------------------------------------------------------------------
# Password hashing (salted scrypt; stdlib, no extra deps)
# ---------------------------------------------------------------------------


def _scrypt(password: str, salt: bytes) -> str:
    derived = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return derived.hex()


def _hash_password(password: str) -> str:
    """Hash a password with a random salt. Returns 'salt_hex$hash_hex'."""
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}${_scrypt(password, salt)}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time verify a password against a stored 'salt$hash'."""
    try:
        salt_hex, expected = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_scrypt(password, salt), expected)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def set_api_key(key: str | None) -> None:
    global _api_key
    _api_key = key or None


def get_api_key() -> str | None:
    return _api_key


def is_api_auth_enabled() -> bool:
    return _api_key is not None


def set_session_secret(secret: str | None) -> None:
    """Set a stable session-signing secret (so cookies survive restarts)."""
    global _session_secret
    if secret:
        _session_secret = secret


def set_dashboard_credentials(username: str | None, password: str | None) -> None:
    global _username, _password_hash
    _username = username or None
    _password_hash = _hash_password(password) if (username and password) else None


def is_dashboard_auth_enabled() -> bool:
    return _username is not None and _password_hash is not None


def is_any_auth_enabled() -> bool:
    return is_api_auth_enabled() or is_dashboard_auth_enabled()


def verify_dashboard_credentials(username: str, password: str) -> bool:
    """Verify dashboard username/password (constant-time)."""
    if not _username or not _password_hash:
        return False
    user_ok = hmac.compare_digest(username, _username)
    pass_ok = _verify_password(password, _password_hash)
    return user_ok and pass_ok


# ---------------------------------------------------------------------------
# Signed session tokens
# ---------------------------------------------------------------------------


def _sign(msg: str) -> str:
    return hmac.new(_session_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def create_session_token() -> str:
    """Create an HMAC-signed session token with an expiry: 'expiry.nonce.sig'."""
    expiry = int(time.time()) + SESSION_TTL_SECONDS
    msg = f"{expiry}.{secrets.token_hex(16)}"
    return f"{msg}.{_sign(msg)}"


def verify_session_token(token: str | None) -> bool:
    """Verify a session token's signature and expiry (constant-time)."""
    if not token:
        return False
    try:
        msg, sig = token.rsplit(".", 1)
        expiry_str, _nonce = msg.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if not hmac.compare_digest(sig, _sign(msg)):
        return False
    return time.time() < expiry


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _api_key_matches(request: Request, credentials: HTTPAuthorizationCredentials | None) -> bool:
    if not _api_key:
        return False
    if credentials and hmac.compare_digest(credentials.credentials, _api_key):
        return True
    x_api_key = request.headers.get("x-api-key")
    if x_api_key and hmac.compare_digest(x_api_key, _api_key):
        return True
    return False


async def require_dashboard_auth(request: Request) -> bool:
    """Dependency: require a valid dashboard session (when dashboard auth is on)."""
    if not is_dashboard_auth_enabled():
        return True
    token = request.cookies.get(SESSION_COOKIE)
    return bool(token and verify_session_token(token))


def get_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


async def verify_api_key(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> bool:
    """Dependency for API-key routes (agents/API clients). 401 on failure."""
    if not _api_key:
        return True
    if _api_key_matches(request, credentials):
        return True
    if request.headers.get("Tailscale-User-Login"):
        return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_api_or_session_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> bool:
    """Dependency for /api routes used by BOTH agents (API key) and the dashboard
    SPA (session cookie). Allows either; 401 if neither and auth is configured."""
    # Fully open only when no auth of any kind is configured.
    if not is_any_auth_enabled():
        return True
    if _api_key_matches(request, credentials):
        return True
    if is_dashboard_auth_enabled():
        token = request.cookies.get(SESSION_COOKIE)
        if token and verify_session_token(token):
            return True
    if request.headers.get("Tailscale-User-Login"):
        return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_websocket_auth(
    websocket_headers: dict[str, str],
    query_params: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> bool:
    """Verify auth for a WebSocket. Accepts API key (header) or a session cookie.

    The query-parameter API-key fallback was removed: query strings leak into
    access logs and browser history.
    """
    if not is_any_auth_enabled():
        return True

    if _api_key:
        auth_header = websocket_headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and hmac.compare_digest(auth_header[7:], _api_key):
            return True
        x_api_key = websocket_headers.get("x-api-key", "")
        if x_api_key and hmac.compare_digest(x_api_key, _api_key):
            return True

    if is_dashboard_auth_enabled() and cookies:
        token = cookies.get(SESSION_COOKIE)
        if token and verify_session_token(token):
            return True

    if websocket_headers.get("tailscale-user-login"):
        return True

    return False
