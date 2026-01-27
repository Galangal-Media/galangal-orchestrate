"""
Hub CLI commands for galangal hub integration.

Commands:
    galangal hub status    - Show hub connection status
    galangal hub test      - Test connection to hub
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def cmd_hub_status(args: argparse.Namespace) -> int:
    """Show hub connection status and configuration."""
    from galangal.config.loader import get_config

    config = get_config()
    hub_config = config.hub

    console.print()
    console.print("[bold]Hub Configuration[/bold]")
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="dim")
    table.add_column("Value")

    table.add_row("Enabled", "[green]Yes[/green]" if hub_config.enabled else "[dim]No[/dim]")
    table.add_row("URL", hub_config.url)
    table.add_row("API Key", "[dim]****[/dim]" if hub_config.api_key else "[dim]Not set[/dim]")
    table.add_row("Heartbeat", f"{hub_config.heartbeat_interval}s")
    table.add_row("Agent Name", hub_config.agent_name or "[dim]<hostname>[/dim]")

    console.print(table)
    console.print()

    if not hub_config.enabled:
        console.print("[yellow]Hub is disabled.[/yellow]")
        console.print()
        console.print("To enable, add to .galangal/config.yaml:")
        console.print()
        console.print("[dim]hub:[/dim]")
        console.print("[dim]  enabled: true[/dim]")
        console.print("[dim]  url: ws://your-hub-server:8080/ws/agent[/dim]")
        console.print()
        return 0

    console.print("[green]Hub is enabled.[/green]")
    console.print("Use [bold]galangal hub test[/bold] to verify the connection.")
    return 0


def cmd_hub_test(args: argparse.Namespace) -> int:
    """Test connection to the hub server."""
    from galangal.config.loader import get_config

    config = get_config()
    hub_config = config.hub

    if not hub_config.enabled:
        console.print("[yellow]Hub is not enabled in configuration.[/yellow]")
        console.print("Add hub.enabled: true to .galangal/config.yaml")
        return 1

    console.print(f"Testing connection to [bold]{hub_config.url}[/bold]...")
    console.print()

    async def test_connection() -> bool:
        from galangal.hub.client import HubClient

        client = HubClient(
            config=hub_config,
            project_name=config.project.name,
            project_path=Path.cwd(),
        )

        try:
            connected = await client.connect()
            if connected:
                console.print("[green]Successfully connected to hub![/green]")
                console.print()
                console.print(f"Agent ID: [bold]{client.agent_info.agent_id}[/bold]")
                console.print(f"Hostname: {client.agent_info.hostname}")
                console.print(f"Project: {client.agent_info.project_name}")
                await client.disconnect()
                return True
            else:
                console.print("[red]Failed to connect to hub.[/red]")
                return False
        except Exception as e:
            console.print(f"[red]Connection error: {e}[/red]")
            return False

    try:
        success = asyncio.run(test_connection())
        return 0 if success else 1
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        return 1


def cmd_hub_info(args: argparse.Namespace) -> int:
    """Show information about the hub server."""
    from galangal.config.loader import get_config

    config = get_config()
    hub_config = config.hub

    if not hub_config.enabled:
        console.print("[yellow]Hub is not enabled.[/yellow]")
        return 1

    # Extract HTTP URL from WebSocket URL
    ws_url = hub_config.url
    if ws_url.startswith("ws://"):
        http_url = "http://" + ws_url[5:].split("/")[0]
    elif ws_url.startswith("wss://"):
        http_url = "https://" + ws_url[6:].split("/")[0]
    else:
        console.print("[red]Invalid hub URL format.[/red]")
        return 1

    console.print(f"Hub URL: [bold]{http_url}[/bold]")
    console.print()
    console.print(f"Dashboard: {http_url}/")
    console.print(f"API: {http_url}/api/")
    console.print(f"WebSocket: {ws_url}")
    return 0
