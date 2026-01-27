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
    """Test connection to the hub server with detailed diagnostics."""
    import socket
    import ssl
    from urllib.parse import urlparse

    from galangal.config.loader import get_config

    config = get_config()
    hub_config = config.hub

    if not hub_config.enabled:
        console.print("[yellow]Hub is not enabled in configuration.[/yellow]")
        console.print("Add hub.enabled: true to .galangal/config.yaml")
        return 1

    console.print(f"[bold]Testing connection to hub[/bold]")
    console.print(f"URL: {hub_config.url}")
    console.print()

    # Parse URL
    parsed = urlparse(hub_config.url)
    use_ssl = parsed.scheme == "wss"
    host = parsed.hostname
    port = parsed.port or (443 if use_ssl else 80)

    if not host:
        console.print("[red]✗ Invalid URL: cannot parse hostname[/red]")
        return 1

    # Step 1: Check websockets module
    console.print("[dim]1. Checking websockets module...[/dim]")
    try:
        import websockets  # noqa: F401

        console.print("[green]✓[/green] websockets module available")
    except ImportError:
        console.print("[red]✗ websockets module not installed[/red]")
        console.print("  Install with: pip install websockets")
        return 1

    # Step 2: DNS resolution
    console.print(f"[dim]2. Resolving hostname {host}...[/dim]")
    try:
        ip_addresses = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ip = ip_addresses[0][4][0]
        console.print(f"[green]✓[/green] DNS resolved to {ip}")
    except socket.gaierror as e:
        console.print(f"[red]✗ DNS resolution failed: {e}[/red]")
        console.print(f"  Check that '{host}' is a valid hostname")
        return 1

    # Step 3: TCP connection
    console.print(f"[dim]3. Testing TCP connection to {host}:{port}...[/dim]")
    try:
        sock = socket.create_connection((host, port), timeout=10)
        sock.close()
        console.print(f"[green]✓[/green] TCP connection successful")
    except socket.timeout:
        console.print(f"[red]✗ TCP connection timed out[/red]")
        console.print(f"  Check firewall rules and that hub is running on port {port}")
        return 1
    except ConnectionRefusedError:
        console.print(f"[red]✗ TCP connection refused[/red]")
        console.print(f"  Hub server may not be running on {host}:{port}")
        return 1
    except OSError as e:
        console.print(f"[red]✗ TCP connection failed: {e}[/red]")
        return 1

    # Step 4: SSL/TLS (if wss://)
    if use_ssl:
        console.print("[dim]4. Testing TLS handshake...[/dim]")
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    console.print(f"[green]✓[/green] TLS handshake successful ({ssock.version()})")
        except ssl.SSLError as e:
            console.print(f"[red]✗ TLS handshake failed: {e}[/red]")
            console.print("  Check SSL certificate validity")
            return 1
    else:
        console.print("[dim]4. Skipping TLS check (using ws://)[/dim]")

    # Step 5: WebSocket connection and authentication
    console.print("[dim]5. Testing WebSocket connection and authentication...[/dim]")

    async def test_websocket() -> tuple[bool, str]:
        import json

        import websockets
        from websockets.exceptions import ConnectionClosed, InvalidStatusCode

        headers = {}
        if hub_config.api_key:
            # Use both Authorization and X-API-Key headers
            # Some proxies (like Cloudflare) may strip Authorization headers
            headers["Authorization"] = f"Bearer {hub_config.api_key}"
            headers["X-API-Key"] = hub_config.api_key

        try:
            async with websockets.connect(
                hub_config.url,
                additional_headers=headers,
                close_timeout=5,
            ) as ws:
                # Send registration
                import platform
                import uuid

                agent_id = str(uuid.uuid4())
                register_msg = {
                    "type": "register",
                    "agent_id": agent_id,
                    "payload": {
                        "agent_id": agent_id,
                        "hostname": platform.node(),
                        "project_name": config.project.name,
                        "project_path": str(Path.cwd()),
                        "agent_name": hub_config.agent_name or platform.node(),
                    },
                }
                await ws.send(json.dumps(register_msg))

                # Wait for acknowledgement
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(response)
                    if data.get("type") == "registered":
                        return True, data.get("agent_id", agent_id)
                    elif data.get("type") == "error":
                        return False, f"Registration rejected: {data.get('message', 'unknown error')}"
                    else:
                        return True, agent_id  # Assume success if no error
                except asyncio.TimeoutError:
                    return False, "Registration timed out (no response from hub)"

        except InvalidStatusCode as e:
            if e.status_code == 403:
                return False, "Authentication failed (403 Forbidden) - check API key"
            elif e.status_code == 401:
                return False, "Authentication required (401 Unauthorized) - API key may be missing"
            elif e.status_code == 404:
                return False, f"WebSocket endpoint not found (404) - check URL path: {parsed.path}"
            else:
                return False, f"HTTP error {e.status_code}"
        except ConnectionClosed as e:
            return False, f"Connection closed by server: {e.reason or 'no reason given'}"
        except Exception as e:
            return False, str(e)

    try:
        success, result = asyncio.run(test_websocket())
    except KeyboardInterrupt:
        console.print("\nCancelled.")
        return 1

    if success:
        console.print("[green]✓[/green] WebSocket connection successful")
        console.print("[green]✓[/green] Agent registration successful")
        console.print()
        console.print("[bold green]All tests passed![/bold green]")
        console.print()
        console.print(f"Agent ID: [bold]{result}[/bold]")
        console.print(f"Project: {config.project.name}")
        if hub_config.api_key:
            console.print("API Key: [dim]****configured[/dim]")
        return 0
    else:
        console.print(f"[red]✗ {result}[/red]")
        console.print()

        # Provide troubleshooting hints based on error
        if "api key" in result.lower() or "auth" in result.lower():
            console.print("[yellow]Troubleshooting hints:[/yellow]")
            console.print("  • Check that HUB_API_KEY on server matches api_key in config")
            console.print("  • Verify api_key is set in .galangal/config.yaml:")
            console.print("    hub:")
            console.print("      api_key: your-api-key")
        elif "404" in result:
            console.print("[yellow]Troubleshooting hints:[/yellow]")
            console.print("  • WebSocket path should be /ws/agent")
            console.print(f"  • Current URL: {hub_config.url}")
            console.print("  • Try: ws://your-server:8080/ws/agent")

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
