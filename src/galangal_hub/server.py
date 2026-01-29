"""
FastAPI server for Galangal Hub.

Provides:
- WebSocket endpoint for agent connections
- REST API for dashboard data
- HTML views for the dashboard UI
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.staticfiles import StaticFiles

from galangal_hub.auth import verify_websocket_auth
from galangal_hub.connection import manager
from galangal_hub.models import (
    AgentInfo,
    MessageType,
    PromptData,
    PromptOption,
    TaskState,
    WorkflowEvent,
)
from galangal_hub.storage import storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - initialize and cleanup resources."""
    # Initialize storage
    await storage.initialize()
    yield
    # Cleanup
    await storage.close()


# Dashboard WebSocket connections for live updates
_dashboard_connections: list[WebSocket] = []


async def notify_dashboards() -> None:
    """Send refresh notification to all connected dashboards."""
    disconnected = []
    for ws in _dashboard_connections:
        try:
            await ws.send_text('{"type": "refresh"}')
        except Exception:
            disconnected.append(ws)

    # Clean up disconnected
    for ws in disconnected:
        if ws in _dashboard_connections:
            _dashboard_connections.remove(ws)


async def notify_dashboards_output(agent_id: str, line: str, line_type: str) -> None:
    """Send output line to all connected dashboards for live streaming."""
    message = json.dumps({
        "type": "output",
        "agent_id": agent_id,
        "line": line,
        "line_type": line_type,
    })

    disconnected = []
    for ws in _dashboard_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)

    # Clean up disconnected
    for ws in disconnected:
        if ws in _dashboard_connections:
            _dashboard_connections.remove(ws)


async def notify_dashboards_prompt(agent_id: str, agent_name: str, prompt: PromptData | None) -> None:
    """Send prompt notification to all connected dashboards."""
    if prompt:
        message = json.dumps({
            "type": "prompt",
            "agent_id": agent_id,
            "agent_name": agent_name,
            "message": prompt.message[:200],  # Truncate for toast
            "prompt_type": prompt.prompt_type,
        })
    else:
        message = json.dumps({
            "type": "prompt_cleared",
            "agent_id": agent_id,
        })

    disconnected = []
    for ws in _dashboard_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)

    # Clean up disconnected
    for ws in disconnected:
        if ws in _dashboard_connections:
            _dashboard_connections.remove(ws)


async def dashboard_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for dashboard live updates.

    This endpoint does NOT require API key authentication - it's for
    browser dashboards that use session cookies for auth.
    """
    await websocket.accept()
    _dashboard_connections.append(websocket)
    logger.info("Dashboard WebSocket connected")

    try:
        while True:
            # Keep connection alive, wait for messages (or disconnect)
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _dashboard_connections:
            _dashboard_connections.remove(websocket)
        logger.info("Dashboard WebSocket disconnected")


async def agent_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for agent connections.

    Protocol:
    1. Agent connects with Authorization header (if API key required)
    2. Agent sends REGISTER message with agent info
    3. Hub acknowledges registration
    4. Agent sends STATE_UPDATE and EVENT messages
    5. Hub sends ACTION messages for remote control
    6. Agent sends HEARTBEAT to maintain connection
    """
    # Verify authentication before accepting connection
    headers = dict(websocket.headers)
    query_params = dict(websocket.query_params)
    if not await verify_websocket_auth(headers, query_params):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket connection rejected: invalid or missing API key")
        return

    await websocket.accept()
    logger.info("WebSocket connection accepted")

    agent_id: str | None = None
    registered_agent_id: str | None = None  # Set once on registration, immutable

    try:
        while True:
            data = await websocket.receive_text()

            # Parse JSON with error handling
            try:
                message = json.loads(data)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON received: {e}")
                continue

            # Validate message type
            try:
                msg_type = MessageType(message.get("type", ""))
            except ValueError:
                logger.warning(f"Unknown message type: {message.get('type')}")
                continue

            payload = message.get("payload", {})

            if msg_type == MessageType.REGISTER:
                # Validate required fields
                required_fields = ["agent_id", "hostname", "project_name", "project_path"]
                missing = [f for f in required_fields if f not in payload]
                if missing:
                    logger.warning(f"Registration missing fields: {missing}")
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": f"Missing fields: {missing}"})
                    )
                    continue

                # Register new agent
                info = AgentInfo(
                    agent_id=payload["agent_id"],
                    hostname=payload["hostname"],
                    project_name=payload["project_name"],
                    project_path=payload["project_path"],
                    agent_name=payload.get("agent_name", payload["hostname"]),
                )
                # Set agent_id once on registration - cannot be changed
                agent_id = info.agent_id
                registered_agent_id = info.agent_id

                await manager.connect(agent_id, websocket, info)
                await storage.upsert_agent(info)

                logger.info(f"Agent registered: {agent_id} ({info.hostname})")

                # Send acknowledgement
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "registered",
                            "agent_id": agent_id,
                        }
                    )
                )

            elif msg_type == MessageType.STATE_UPDATE:
                # Must be registered first
                if not registered_agent_id:
                    logger.warning("STATE_UPDATE received before registration")
                    continue

                # Use the registered agent_id, ignore any agent_id in message
                agent_id = registered_agent_id

                # Handle IDLE state (no task) - clear task state
                if payload.get("stage") == "IDLE" or payload.get("task_name") is None:
                    previous_state = await manager.update_task_state(agent_id, None)
                    # If previous task was active (not completed), record completion as abandoned
                    if previous_state and previous_state.stage != "COMPLETE":
                        await storage.record_task_complete(
                            agent_id=agent_id,
                            task_name=previous_state.task_name,
                            final_stage=previous_state.stage,
                            success=False,
                            metadata={"status": "abandoned"},
                        )
                    logger.info(f"Agent {agent_id}: now idle (no active task)")
                    continue

                # Validate required fields for active task
                if "task_name" not in payload or "stage" not in payload:
                    logger.warning("STATE_UPDATE missing task_name or stage")
                    continue

                state = TaskState(
                    task_name=payload["task_name"],
                    task_description=payload.get("task_description", ""),
                    task_type=payload.get("task_type", "feature"),
                    stage=payload["stage"],
                    attempt=payload.get("attempt", 1),
                    awaiting_approval=payload.get("awaiting_approval", False),
                    last_failure=payload.get("last_failure"),
                    started_at=payload.get("started_at", datetime.now(timezone.utc).isoformat()),
                    stage_durations=payload.get("stage_durations"),
                    github_issue=payload.get("github_issue"),
                    github_repo=payload.get("github_repo"),
                )
                previous_state = await manager.update_task_state(agent_id, state)

                # Check if this is a new task (task name changed or no previous task)
                is_new_task = (
                    previous_state is None or
                    previous_state.task_name != state.task_name
                )

                if is_new_task:
                    # If previous task existed and wasn't completed, mark it
                    if previous_state and previous_state.stage != "COMPLETE":
                        await storage.record_task_complete(
                            agent_id=agent_id,
                            task_name=previous_state.task_name,
                            final_stage=previous_state.stage,
                            success=False,
                            metadata={"status": "superseded"},
                        )
                    # Record new task start
                    await storage.record_task_start(agent_id, state)
                    logger.info(f"Agent {agent_id}: started task '{state.task_name}'")

                # Check if task just completed
                if state.stage == "COMPLETE":
                    await storage.record_task_complete(
                        agent_id=agent_id,
                        task_name=state.task_name,
                        final_stage="COMPLETE",
                        success=True,
                    )
                    logger.info(f"Agent {agent_id}: completed task '{state.task_name}'")

            elif msg_type == MessageType.EVENT:
                # Must be registered first
                if not registered_agent_id:
                    logger.warning("EVENT received before registration")
                    continue

                agent_id = registered_agent_id

                # Validate required fields
                if "event_type" not in payload or "timestamp" not in payload:
                    logger.warning("EVENT missing event_type or timestamp")
                    continue

                try:
                    event = WorkflowEvent(
                        event_type=payload["event_type"],
                        timestamp=datetime.fromisoformat(payload["timestamp"]),
                        agent_id=agent_id,
                        task_name=payload.get("task_name"),
                        data=payload.get("data", {}),
                    )
                    await storage.record_event(event)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid event data: {e}")

            elif msg_type == MessageType.HEARTBEAT:
                # Must be registered first
                if not registered_agent_id:
                    continue

                agent_id = registered_agent_id
                await manager.update_heartbeat(agent_id)
                await storage.update_agent_seen(agent_id)

            elif msg_type == MessageType.PROMPT:
                # Must be registered first
                if not registered_agent_id:
                    logger.warning("PROMPT received before registration")
                    continue

                agent_id = registered_agent_id

                # Get agent name for notification
                agent = manager.get_agent(agent_id)
                agent_name = agent.agent.agent_name if agent else "Agent"

                # Check if prompt is being cleared
                if payload.get("prompt_type") is None:
                    await manager.clear_prompt(agent_id)
                    await notify_dashboards_prompt(agent_id, agent_name, None)
                    logger.info(f"Agent {agent_id}: prompt cleared")
                else:
                    # Parse prompt data
                    try:
                        options = [
                            PromptOption(
                                key=opt.get("key", ""),
                                label=opt.get("label", ""),
                                result=opt.get("result", ""),
                                color=opt.get("color"),
                            )
                            for opt in payload.get("options", [])
                        ]
                        prompt = PromptData(
                            prompt_type=payload["prompt_type"],
                            message=payload.get("message", ""),
                            options=options,
                            questions=payload.get("questions", []),
                            artifacts=payload.get("artifacts", []),
                            context=payload.get("context", {}),
                        )
                        await manager.update_prompt(agent_id, prompt)
                        await notify_dashboards_prompt(agent_id, agent_name, prompt)
                        logger.info(f"Agent {agent_id}: prompt updated - {prompt.prompt_type}")
                    except (KeyError, TypeError, ValueError) as e:
                        logger.warning(f"Invalid PROMPT data: {e}")

            elif msg_type == MessageType.ARTIFACTS:
                # Must be registered first
                if not registered_agent_id:
                    logger.warning("ARTIFACTS received before registration")
                    continue

                agent_id = registered_agent_id
                artifacts = payload.get("artifacts", {})
                if artifacts and isinstance(artifacts, dict):
                    await manager.update_artifacts(agent_id, artifacts)
                    logger.info(f"Agent {agent_id}: artifacts updated - {list(artifacts.keys())}")

            elif msg_type == MessageType.GITHUB_ISSUES:
                # Must be registered first
                if not registered_agent_id:
                    logger.warning("GITHUB_ISSUES received before registration")
                    continue

                agent_id = registered_agent_id
                issues = payload.get("issues", [])
                if isinstance(issues, list):
                    await manager.update_github_issues(agent_id, issues)
                    logger.info(f"Agent {agent_id}: received {len(issues)} GitHub issues")

            elif msg_type == MessageType.OUTPUT:
                # Must be registered first
                if not registered_agent_id:
                    continue  # Silently skip - too noisy to log

                agent_id = registered_agent_id
                line = payload.get("line", "")
                line_type = payload.get("line_type", "raw")
                await manager.append_output(agent_id, line, line_type)
                # Push to dashboards immediately for live updates
                await notify_dashboards_output(agent_id, line, line_type)

    except WebSocketDisconnect:
        logger.info(f"Agent disconnected: {agent_id}")
    except Exception as e:
        logger.exception(f"WebSocket error for agent {agent_id}: {e}")
    finally:
        if agent_id:
            await manager.disconnect(agent_id)


def create_app(
    db_path: str | Path = "hub.db",
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        db_path: Path to SQLite database.

    Returns:
        Configured FastAPI application.
    """
    # Configure storage path BEFORE creating app (so lifespan uses correct path)
    storage.db_path = Path(db_path)

    app = FastAPI(
        title="Galangal Hub",
        description="Centralized dashboard for remote monitoring and control of galangal workflows",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register API routes
    from galangal_hub.api import actions, agents, tasks

    app.include_router(agents.router)
    app.include_router(tasks.router)
    app.include_router(actions.router)

    # Mount React SPA
    from galangal_hub.spa import get_spa_router, mount_spa_static

    # Mount SPA static assets
    mount_spa_static(app)

    # Register auth routes (login still uses Jinja2 for simplicity)
    from galangal_hub import views
    app.include_router(views.login_router)

    # SPA routes
    app.include_router(get_spa_router())

    # Register WebSocket routes
    app.websocket("/ws/dashboard")(dashboard_websocket)
    app.websocket("/ws/agent")(agent_websocket)

    # Register dashboard notification callback
    manager.on_change(notify_dashboards)

    return app


# Default app instance (for module-level imports)
app = create_app()
