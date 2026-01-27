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

                # Validate required fields
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
                await manager.update_task_state(agent_id, state)

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

                # Check if prompt is being cleared
                if payload.get("prompt_type") is None:
                    await manager.clear_prompt(agent_id)
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
                            artifacts=payload.get("artifacts", []),
                            context=payload.get("context", {}),
                        )
                        await manager.update_prompt(agent_id, prompt)
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

    except WebSocketDisconnect:
        logger.info(f"Agent disconnected: {agent_id}")
    except Exception as e:
        logger.exception(f"WebSocket error for agent {agent_id}: {e}")
    finally:
        if agent_id:
            await manager.disconnect(agent_id)


def create_app(
    db_path: str | Path = "hub.db",
    static_dir: str | Path | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        db_path: Path to SQLite database.
        static_dir: Path to static files directory (optional).

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

    # Mount static files if directory provided
    if static_dir:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Register HTTP routes
    from galangal_hub import views
    from galangal_hub.api import actions, agents, tasks

    app.include_router(agents.router)
    app.include_router(tasks.router)
    app.include_router(actions.router)
    app.include_router(views.router)

    # Register WebSocket routes
    app.websocket("/ws/dashboard")(dashboard_websocket)
    app.websocket("/ws/agent")(agent_websocket)

    # Register dashboard notification callback
    manager.on_change(notify_dashboards)

    return app


# Default app instance (for module-level imports)
app = create_app()
