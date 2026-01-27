"""
Hub client for connecting to Galangal Hub server.

Provides WebSocket-based communication for remote monitoring and control.
"""

from galangal.hub.client import HubClient
from galangal.hub.config import HubConfig

__all__ = ["HubClient", "HubConfig"]
