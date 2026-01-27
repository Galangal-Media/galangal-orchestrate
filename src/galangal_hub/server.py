"""
FastAPI server for Galangal Hub.

Provides:
- WebSocket endpoint for agent connections
- REST API for dashboard data
- HTML views for the dashboard UI
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from galangal_hub.connection import manager
from galangal_hub.models import AgentInfo, MessageType, TaskState, WorkflowEvent
from galangal_hub.storage import storage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - initialize and cleanup resources."""
    # Initialize storage
    await storage.initialize()
    yield
    # Cleanup
    await storage.close()


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
    app = FastAPI(
        title="Galangal Hub",
        description="Centralized dashboard for remote monitoring and control of galangal workflows",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Configure storage path
    storage.db_path = Path(db_path)

    # Mount static files if directory provided
    if static_dir:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Register routes
    from galangal_hub.api import agents, tasks, actions
    from galangal_hub import views

    app.include_router(agents.router)
    app.include_router(tasks.router)
    app.include_router(actions.router)
    app.include_router(views.router)

    return app


# Default app instance
app = create_app()


@app.websocket("/ws/agent")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for agent connections.

    Protocol:
    1. Agent connects
    2. Agent sends REGISTER message with agent info
    3. Hub acknowledges registration
    4. Agent sends STATE_UPDATE and EVENT messages
    5. Hub sends ACTION messages for remote control
    6. Agent sends HEARTBEAT to maintain connection
    """
    await websocket.accept()

    agent_id: str | None = None

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = MessageType(message.get("type", ""))
            payload = message.get("payload", {})
            agent_id = message.get("agent_id", agent_id)

            if msg_type == MessageType.REGISTER:
                # Register new agent
                info = AgentInfo(
                    agent_id=payload["agent_id"],
                    hostname=payload["hostname"],
                    project_name=payload["project_name"],
                    project_path=payload["project_path"],
                    agent_name=payload.get("agent_name", payload["hostname"]),
                )
                agent_id = info.agent_id
                await manager.connect(agent_id, websocket, info)
                await storage.upsert_agent(info)

                # Send acknowledgement
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "registered",
                            "agent_id": agent_id,
                        }
                    )
                )

            elif msg_type == MessageType.STATE_UPDATE and agent_id:
                # Update task state
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

            elif msg_type == MessageType.EVENT and agent_id:
                # Record workflow event
                event = WorkflowEvent(
                    event_type=payload["event_type"],
                    timestamp=datetime.fromisoformat(payload["timestamp"]),
                    agent_id=agent_id,
                    task_name=payload.get("task_name"),
                    data=payload.get("data", {}),
                )
                await storage.record_event(event)

            elif msg_type == MessageType.HEARTBEAT and agent_id:
                # Update last seen time
                await manager.update_heartbeat(agent_id)
                await storage.update_agent_seen(agent_id)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if agent_id:
            await manager.disconnect(agent_id)
