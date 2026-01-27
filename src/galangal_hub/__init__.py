"""
Galangal Hub - Centralized dashboard for remote monitoring and control.

A FastAPI-based server that agents connect to via WebSocket for:
- Real-time state monitoring
- Remote approval/rejection of stages
- Multi-repo/machine workflow visibility
"""

from pathlib import Path


def _read_version() -> str:
    """Read version from VERSION file."""
    # Try various locations (Docker vs development)
    locations = [
        Path("/app/VERSION"),  # Docker location
        Path(__file__).parent.parent.parent / "VERSION",  # src/../VERSION (dev)
        Path(__file__).parent.parent / "VERSION",  # Installed location
    ]
    for path in locations:
        if path.exists():
            return path.read_text().strip()
    return "0.0.0"


__version__ = _read_version()
