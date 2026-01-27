"""
Authentication for Galangal Hub.

Supports:
- API key authentication
- Tailscale authentication (checking peer identity)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Optional API key for authentication
_api_key: str | None = None

security = HTTPBearer(auto_error=False)


def set_api_key(key: str | None) -> None:
    """Set the API key for authentication."""
    global _api_key
    _api_key = key


def get_api_key() -> str | None:
    """Get the configured API key."""
    return _api_key


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
) -> bool:
    """
    Verify authentication for WebSocket connections.

    Args:
        websocket_headers: Headers from the WebSocket connection.

    Returns:
        True if authenticated, False otherwise.
    """
    # If no API key configured, allow all
    if not _api_key:
        return True

    # Check Authorization header
    auth_header = websocket_headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == _api_key:
            return True

    # Check Tailscale headers
    if websocket_headers.get("tailscale-user-login"):
        return True

    return False
