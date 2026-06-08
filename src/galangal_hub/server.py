"""
FastAPI server for Galangal Hub.

Provides:
- WebSocket endpoint for agent connections
- REST API for dashboard data
- HTML views for the dashboard UI
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

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

    # Initialize environment subsystem
    from galangal_hub.environments.process_manager import process_manager
    from galangal_hub.environments.routes import set_env_storage
    from galangal_hub.environments.storage import EnvironmentStorage

    if storage._db:
        env_storage = EnvironmentStorage(storage._db)
        set_env_storage(env_storage)
        await process_manager.restore_on_startup(env_storage)

    yield

    # Cleanup
    from galangal_hub.environments.process_manager import process_manager as pm

    await pm.stop_all()
    await storage.close()


# Limits to bound resource use from clients.
MAX_WS_MESSAGE_BYTES = 1_000_000  # 1 MB per inbound frame
MAX_DASHBOARD_CONNECTIONS = 100

# Dashboard WebSocket connections for live updates, guarded by a lock so concurrent
# coroutines (broadcasts + connect/disconnect) don't mutate the list mid-iteration.
_dashboard_connections: list[WebSocket] = []
_dashboard_lock = asyncio.Lock()


async def _add_dashboard_connection(ws: WebSocket) -> bool:
    async with _dashboard_lock:
        if len(_dashboard_connections) >= MAX_DASHBOARD_CONNECTIONS:
            return False
        _dashboard_connections.append(ws)
        return True


async def _remove_dashboard_connection(ws: WebSocket) -> None:
    async with _dashboard_lock:
        if ws in _dashboard_connections:
            _dashboard_connections.remove(ws)


async def _broadcast_to_dashboards(message: str) -> None:
    """Send a message to every dashboard, dropping any that fail (lock-safe)."""
    async with _dashboard_lock:
        targets = list(_dashboard_connections)
    disconnected = []
    for ws in targets:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    if disconnected:
        async with _dashboard_lock:
            for ws in disconnected:
                if ws in _dashboard_connections:
                    _dashboard_connections.remove(ws)


async def notify_dashboards() -> None:
    """Send refresh notification to all connected dashboards."""
    await _broadcast_to_dashboards('{"type": "refresh"}')


async def notify_dashboards_output(agent_id: str, line: str, line_type: str) -> None:
    """Send output line to all connected dashboards for live streaming."""
    await _broadcast_to_dashboards(json.dumps({
        "type": "output",
        "agent_id": agent_id,
        "line": line,
        "line_type": line_type,
    }))


async def notify_dashboards_prompt(agent_id: str, agent_name: str, prompt: PromptData | None) -> None:
    """Send prompt notification to all connected dashboards."""
    if prompt:
        # context may be any JSON value from the agent - don't assume dict.
        context = prompt.context if isinstance(prompt.context, dict) else {}
        prompt_dict = {
            "prompt_type": prompt.prompt_type,
            "message": prompt.message,
            "options": [
                {"key": opt.key, "label": opt.label, "result": opt.result, "color": opt.color}
                for opt in prompt.options
            ],
            "questions": prompt.questions,
            "artifacts": prompt.artifacts,
            "context": prompt.context,
        }
        message = json.dumps({
            "type": "prompt",
            "agent_id": agent_id,
            "agent_name": agent_name,
            "task_name": context.get("task_name", "_"),
            "prompt": prompt_dict,
            # Keep these for backwards compatibility with toast
            "message": prompt.message[:200],
            "prompt_type": prompt.prompt_type,
        })
    else:
        message = json.dumps({
            "type": "prompt_cleared",
            "agent_id": agent_id,
        })

    await _broadcast_to_dashboards(message)


async def dashboard_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for dashboard live updates.

    Authenticated via the session cookie (browser) or API key, the same as the
    REST API. Streams live agent output/state, so it must not be open to all.
    """
    if not await verify_websocket_auth(
        dict(websocket.headers), dict(websocket.query_params), dict(websocket.cookies)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("Dashboard WebSocket rejected: not authenticated")
        return

    await websocket.accept()
    if not await _add_dashboard_connection(websocket):
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        logger.warning("Dashboard WebSocket rejected: connection cap reached")
        return
    logger.info("Dashboard WebSocket connected")

    try:
        while True:
            # Keep connection alive, wait for messages (or disconnect). Cap frame
            # size to avoid an unbounded-memory DoS from a misbehaving client.
            msg = await websocket.receive_text()
            if len(msg) > MAX_WS_MESSAGE_BYTES:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break
    except WebSocketDisconnect:
        pass
    finally:
        await _remove_dashboard_connection(websocket)
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
    if not await verify_websocket_auth(headers, query_params, dict(websocket.cookies)):
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
            if len(data) > MAX_WS_MESSAGE_BYTES:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break

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

                if not await manager.connect(agent_id, websocket, info):
                    # Another live connection already owns this agent_id.
                    await websocket.send_text(
                        json.dumps({
                            "type": "error",
                            "message": f"agent_id '{agent_id}' is already connected",
                        })
                    )
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                await storage.upsert_agent(info)

                # Link agent to environment by matching project_path to local_path
                try:
                    from galangal_hub.environments import routes as env_routes

                    if env_routes._env_storage:
                        env_id_linked = await env_routes._env_storage.set_environment_agent_by_path(
                            info.project_path, agent_id
                        )
                        if env_id_linked:
                            logger.info(
                                f"Linked agent {agent_id} to environment {env_id_linked}"
                            )
                except Exception as e:
                    logger.warning(f"Failed to link agent to environment: {e}")

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
                replace = bool(payload.get("replace", False))
                if isinstance(artifacts, dict):
                    await manager.update_artifacts(agent_id, artifacts, replace=replace)
                    # Persist artifacts by task for restart-safe retrieval in task views.
                    task_name = payload.get("task_name")
                    if not task_name:
                        agent = manager.get_agent(agent_id)
                        if agent and agent.task:
                            task_name = agent.task.task_name
                    if task_name:
                        await storage.upsert_task_artifacts(
                            agent_id=agent_id,
                            task_name=str(task_name),
                            artifacts=artifacts,
                            replace=replace,
                        )
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

    # Register API routes. Every /api router requires auth (API key for agents,
    # session cookie for the dashboard SPA); open only when no auth is configured.
    from fastapi import Depends

    from galangal_hub.api import actions, agents, tasks
    from galangal_hub.auth import require_api_or_session_auth

    api_auth = [Depends(require_api_or_session_auth)]
    app.include_router(agents.router, dependencies=api_auth)
    app.include_router(tasks.router, dependencies=api_auth)
    app.include_router(actions.router, dependencies=api_auth)

    # Environment routes
    from galangal_hub.environments.routes import router as env_router

    app.include_router(env_router, dependencies=api_auth)

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

    # Terminal WebSocket for Claude account login
    from galangal_hub.environments.routes import claude_account_terminal

    app.websocket("/ws/claude-accounts/{account_id}/terminal")(
        claude_account_terminal
    )

    # Register dashboard notification callback
    manager.on_change(notify_dashboards)

    return app


# Default app instance (for module-level imports)
app = create_app()
