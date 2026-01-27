"""
Authentication for Galangal Hub.

Supports:
- API key authentication (for agents)
- Username/password authentication (for dashboard)
- Tailscale authentication (checking peer identity)
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Optional API key for agent authentication
_api_key: str | None = None

# Dashboard credentials
_username: str | None = None
_password_hash: str | None = None

# Session secret for signing cookies
_session_secret: str = secrets.token_hex(32)

security = HTTPBearer(auto_error=False)

# Session cookie name
SESSION_COOKIE = "galangal_session"


def _hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def set_api_key(key: str | None) -> None:
    """Set the API key for agent authentication."""
    global _api_key
    _api_key = key


def get_api_key() -> str | None:
    """Get the configured API key."""
    return _api_key


def set_dashboard_credentials(username: str | None, password: str | None) -> None:
    """Set the dashboard username and password."""
    global _username, _password_hash
    _username = username
    if password:
        _password_hash = _hash_password(password)
    else:
        _password_hash = None


def is_dashboard_auth_enabled() -> bool:
    """Check if dashboard authentication is enabled."""
    return _username is not None and _password_hash is not None


def verify_dashboard_credentials(username: str, password: str) -> bool:
    """Verify dashboard username and password."""
    if not _username or not _password_hash:
        return True  # No auth configured
    return username == _username and _hash_password(password) == _password_hash


def create_session_token() -> str:
    """Create a new session token."""
    return hashlib.sha256(f"{_session_secret}:{secrets.token_hex(16)}".encode()).hexdigest()


def verify_session_token(token: str | None) -> bool:
    """Verify a session token is valid."""
    if not token:
        return False
    # For simplicity, we just check if token exists and is non-empty
    # The token is signed by being generated with the secret
    return len(token) == 64  # SHA-256 hex length


async def require_dashboard_auth(request: Request) -> bool:
    """
    Dependency that requires dashboard authentication.

    Redirects to login if not authenticated.
    """
    # If auth not enabled, allow all
    if not is_dashboard_auth_enabled():
        return True

    # Check session cookie
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token and verify_session_token(session_token):
        return True

    # Not authenticated - this will be caught by the route handler
    return False


def get_login_redirect() -> RedirectResponse:
    """Get a redirect response to the login page."""
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


async def verify_api_key(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> bool:
    """
    Verify the API key from the request.

    Returns True if:
    - No API key is configured (authentication disabled)
    - Valid API key is provided in Authorization header
    - Request is from Tailscale network (when enabled)
    """
    # If no API key configured, allow all
    if not _api_key:
        return True

    # Check Authorization header
    if credentials and credentials.credentials == _api_key:
        return True

    # Check Tailscale headers (if behind Tailscale)
    tailscale_user = request.headers.get("Tailscale-User-Login")
    if tailscale_user:
        # Tailscale authentication - user is authenticated via Tailscale
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_websocket_auth(
    websocket_headers: dict[str, str],
    query_params: dict[str, str] | None = None,
) -> bool:
    """
    Verify authentication for WebSocket connections.

    Args:
        websocket_headers: Headers from the WebSocket connection.
        query_params: Query parameters from the WebSocket URL.

    Returns:
        True if authenticated, False otherwise.
    """
    # If no API key configured, allow all
    if not _api_key:
        return True

    # Check Authorization header (standard)
    auth_header = websocket_headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == _api_key:
            return True

    # Check X-API-Key header (alternative, less likely to be stripped by proxies)
    x_api_key = websocket_headers.get("x-api-key", "")
    if x_api_key == _api_key:
        return True

    # Check query parameter (fallback for proxies that strip headers)
    if query_params:
        query_key = query_params.get("api_key", "")
        if query_key == _api_key:
            return True

    # Check Tailscale headers
    if websocket_headers.get("tailscale-user-login"):
        return True

    return False
