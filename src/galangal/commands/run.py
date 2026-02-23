"""
galangal run - Run as a hub agent daemon.

Connects to the hub, registers, sends idle state, and waits for
CREATE_TASK actions. When a task is received, runs the workflow,
then returns to idle.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from rich.console import Console

console = Console()


def cmd_run(args: argparse.Namespace) -> int:
    """Run as a hub agent, waiting for tasks from the hub."""
    from galangal.config.loader import require_initialized

    if not require_initialized():
        return 1

    hub_url = args.hub_url

    try:
        return asyncio.run(_run_agent_loop(hub_url))
    except KeyboardInterrupt:
        console.print("\n[dim]Agent stopped.[/dim]")
        return 0


async def _run_agent_loop(hub_url: str | None) -> int:
    """Main agent loop: connect to hub, wait for tasks, execute them."""
    from galangal.config.loader import get_config
    from galangal.hub.action_handler import get_action_handler
    from galangal.hub.client import HubClient, set_hub_client
    from galangal.hub.hooks import set_main_loop

    config = get_config()

    # Override hub config for agent mode
    config.hub.enabled = True
    if hub_url:
        config.hub.url = hub_url

    set_main_loop(asyncio.get_running_loop())

    project_path = Path.cwd()
    client = HubClient(
        config=config.hub,
        project_name=config.project.name,
        project_path=project_path,
    )

    # Register action handler
    handler = get_action_handler()
    client.on_action(handler.handle_hub_action)

    console.print(f"[bold]Galangal Agent[/bold]")
    console.print(f"  Project: {config.project.name}")
    console.print(f"  Hub URL: {config.hub.url}")
    console.print()

    # Connect
    connected = await client.connect()
    if not connected:
        console.print("[red]Failed to connect to hub.[/red]")
        console.print(f"  URL: {config.hub.url}")
        console.print("  Check that the hub is running and accessible.")
        return 1

    set_hub_client(client)
    console.print("[green]Connected to hub.[/green]")

    # Send idle state
    await client.send_idle_state()
    console.print("[dim]Waiting for tasks...[/dim]")

    # Set up graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Main loop: wait for tasks
    try:
        while not stop_event.is_set():
            # Check for pending task creation
            pending = handler.get_pending_task_create()
            if pending:
                console.print(f"[bold green]Received task from hub[/bold green]")
                await _execute_task(config, client, pending)
                # After task completes, signal idle again
                await client.send_idle_state()
                console.print("[dim]Waiting for tasks...[/dim]")
            else:
                # Brief sleep to avoid busy-wait
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

            # Check connection health
            if not client.connected:
                console.print("[yellow]Disconnected from hub, reconnecting...[/yellow]")
                connected = await client.connect()
                if connected:
                    await client.send_idle_state()
                    console.print("[green]Reconnected.[/green]")
                else:
                    await asyncio.sleep(5)
    finally:
        await client.disconnect()
        console.print("[dim]Disconnected from hub.[/dim]")

    return 0


async def _execute_task(config, client, pending_task) -> None:
    """Execute a task received from the hub.

    Uses the headless workflow runner to avoid needing a TTY/terminal.
    The hub client stays connected in the same event loop, so output
    and prompts are streamed to the hub dashboard in real time.
    """
    from galangal.commands.start import create_task
    from galangal.core.state import TaskType, load_state
    from galangal.core.tasks import generate_unique_task_name, set_active_task
    from galangal.core.workflow.headless_runner import run_workflow_headless

    task_name = pending_task.task_name
    task_description = pending_task.task_description or ""
    task_type_str = pending_task.task_type or "feature"
    github_issue = pending_task.github_issue
    github_repo = pending_task.github_repo

    # Resolve task type
    try:
        task_type = TaskType(task_type_str)
    except ValueError:
        task_type = TaskType.FEATURE

    # Generate task name if not provided
    if not task_name:
        if github_issue and github_repo:
            task_name = generate_unique_task_name(f"issue-{github_issue}")
        else:
            task_name = generate_unique_task_name(task_description[:50] if task_description else "task")

    console.print(f"  Task: [bold]{task_name}[/bold]")
    console.print(f"  Type: {task_type.value}")
    if task_description:
        console.print(f"  Description: {task_description[:100]}")

    # Create the task
    success, msg = create_task(
        task_name=task_name,
        description=task_description,
        task_type=task_type,
        github_issue=github_issue,
        github_repo=github_repo,
    )

    if not success:
        console.print(f"[red]Failed to create task: {msg}[/red]")
        return

    console.print(f"[green]{msg}[/green]")

    # Load state and run workflow
    state = load_state(task_name)
    if not state:
        console.print("[red]Failed to load task state.[/red]")
        return

    # Send state update to hub
    await client.send_state(state)

    # Run the workflow headlessly (async, stays in this event loop)
    try:
        result = await run_workflow_headless(state)
        console.print(f"[bold]Task completed with result: {result}[/bold]")
    except Exception as e:
        console.print(f"[red]Task failed: {e}[/red]")
