"""
CLI for Galangal Hub server.

Usage:
    galangal-hub serve [--port PORT] [--host HOST] [--db PATH]
    galangal-hub init [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the hub server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Install with: pip install galangal-orchestrate[hub]")
        return 1

    from galangal_hub.server import create_app

    # Create app with configuration
    app = create_app(
        db_path=args.db,
        static_dir=Path(__file__).parent / "static" if (Path(__file__).parent / "static").exists() else None,
    )

    print(f"Starting Galangal Hub on http://{args.host}:{args.port}")
    print(f"Database: {args.db}")
    print("Press Ctrl+C to stop")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
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
