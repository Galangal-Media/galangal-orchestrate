"""
Hub configuration model.
"""

from pydantic import BaseModel, Field


class HubConfig(BaseModel):
    """Configuration for connecting to Galangal Hub."""

    enabled: bool = Field(
        default=False,
        description="Enable connection to Galangal Hub",
    )
    url: str = Field(
        default="ws://localhost:8080/ws/agent",
        description="WebSocket URL of the hub server",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authentication (optional)",
    )
    heartbeat_interval: int = Field(
        default=30,
        description="Heartbeat interval in seconds",
    )
    reconnect_interval: int = Field(
        default=5,
        description="Reconnection interval in seconds after disconnect",
    )
    agent_name: str | None = Field(
        default=None,
        description="Custom agent name (defaults to hostname)",
    )
