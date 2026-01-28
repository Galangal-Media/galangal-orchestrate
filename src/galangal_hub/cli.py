"""
CLI for Galangal Hub server.

Usage:
    galangal-hub serve [--port PORT] [--host HOST] [--db PATH]
    galangal-hub init [--force]

Environment Variables:
    HUB_HOST        Host to bind to (default: 0.0.0.0)
    HUB_PORT        Port to listen on (default: 8080)
    HUB_DB_PATH     SQLite database path (default: /data/hub.db)
    HUB_API_KEY     API key for agent authentication (optional)
    HUB_USERNAME    Dashboard username (optional, enables login)
    HUB_PASSWORD    Dashboard password (required if HUB_USERNAME is set)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the hub server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Install with: pip install galangal-orchestrate[hub]")
        return 1

    from galangal_hub.auth import set_api_key, set_dashboard_credentials
    from galangal_hub.server import create_app

    # Read configuration from environment variables (with CLI args as fallback)
    host = os.environ.get("HUB_HOST", args.host)
    port = int(os.environ.get("HUB_PORT", args.port))
    db_path = os.environ.get("HUB_DB_PATH", args.db)
    api_key = os.environ.get("HUB_API_KEY")
    username = os.environ.get("HUB_USERNAME")
    password = os.environ.get("HUB_PASSWORD")

    # Set API key for agent authentication
    if api_key:
        set_api_key(api_key)

    # Set dashboard credentials
    if username:
        if not password:
            print("Error: HUB_PASSWORD is required when HUB_USERNAME is set")
            return 1
        set_dashboard_credentials(username, password)
        print(f"Dashboard authentication enabled (username: {username})")
    else:
        print("Dashboard authentication disabled (set HUB_USERNAME and HUB_PASSWORD to enable)")

    # Create app with configuration
    app = create_app(db_path=db_path)

    # Print version
    from galangal_hub import __version__
    print(f"Galangal Hub v{__version__}")

    print(f"Starting on http://{host}:{port}")
    print(f"Database: {db_path}")
    if api_key:
        print("Agent API key authentication enabled")
    print("Press Ctrl+C to stop")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize hub configuration."""
    config_path = Path("hub-config.yaml")

    if config_path.exists() and not args.force:
        print(f"Configuration file already exists: {config_path}")
        print("Use --force to overwrite")
        return 1

    config_content = """\
# Galangal Hub Configuration

# Server settings
host: "0.0.0.0"
port: 8080

# Database
database: "hub.db"

# Authentication (optional)
# api_key: "your-secret-key"

# Tailscale integration (optional)
# When enabled, only allows connections from Tailscale network
# tailscale:
#   enabled: true
#   network: "tailnet-name"
"""

    config_path.write_text(config_content)
    print(f"Created configuration file: {config_path}")
    print("\nEdit this file to configure your hub, then run:")
    print("  galangal-hub serve")
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="galangal-hub",
        description="Galangal Hub - Centralized monitoring and control for galangal workflows",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the hub server")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080)",
    )
    serve_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--db",
        default="hub.db",
        help="SQLite database path (default: hub.db)",
    )
    serve_parser.set_defaults(func=cmd_serve)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize hub configuration")
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration",
    )
    init_parser.set_defaults(func=cmd_init)

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
