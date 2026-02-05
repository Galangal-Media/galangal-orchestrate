"""
Galangal Hub - Centralized dashboard for remote monitoring and control.

A FastAPI-based server that agents connect to via WebSocket for:
- Real-time state monitoring
- Remote approval/rejection of stages
- Multi-repo/machine workflow visibility
"""

from pathlib import Path


def _read_version() -> str:
    """Read version from package metadata or VERSION file."""
    # First, try to read from installed package metadata (works after pip install)
    try:
        from importlib.metadata import version

        return version("galangal-orchestrate")
    except Exception:
        pass

    # Fallback: try VERSION file (for Docker and development)
    locations = [
        Path("/app/VERSION"),  # Docker location
        Path(__file__).parent.parent.parent / "VERSION",  # src/../VERSION (dev)
    ]
    for path in locations:
        if path.exists():
            return path.read_text().strip()

    return "0.0.0"


__version__ = _read_version()
