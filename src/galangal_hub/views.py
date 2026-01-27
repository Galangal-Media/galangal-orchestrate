"""
HTML views for the dashboard UI.

Uses Jinja2 templates with HTMX for interactivity.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from galangal_hub.connection import manager
from galangal_hub.storage import storage

router = APIRouter(tags=["views"])

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Main dashboard view."""
    agents = manager.get_connected_agents()
    needs_attention = manager.get_agents_needing_attention()
    recent_tasks = await storage.get_recent_tasks(limit=10)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "agents": agents,
            "needs_attention": needs_attention,
            "recent_tasks": recent_tasks,
        },
    )


@router.get("/agent/{agent_id}", response_class=HTMLResponse)
async def agent_detail(request: Request, agent_id: str) -> HTMLResponse:
    """Agent detail view."""
    agent = manager.get_agent(agent_id)
    if not agent:
        return templates.TemplateResponse(
            "404.html",
            {"request": request, "message": "Agent not found"},
            status_code=404,
        )

    events = await storage.get_recent_events(agent_id=agent_id, limit=50)
    tasks = await storage.get_recent_tasks(agent_id=agent_id, limit=20)

    return templates.TemplateResponse(
        "agent_detail.html",
        {
            "request": request,
            "agent": agent,
            "events": events,
            "tasks": tasks,
        },
    )


@router.get("/task/{agent_id}/{task_name}", response_class=HTMLResponse)
async def task_detail(request: Request, agent_id: str, task_name: str) -> HTMLResponse:
    """Task detail view."""
    agent = manager.get_agent(agent_id)

    # Check if it's an active task
    if agent and agent.task and agent.task.task_name == task_name:
        events = await storage.get_recent_events(agent_id=agent_id, limit=50)
        return templates.TemplateResponse(
            "task_detail.html",
            {
                "request": request,
                "agent": agent,
                "task": agent.task,
                "events": events,
                "active": True,
            },
        )

    # Check historical tasks
    tasks = await storage.get_recent_tasks(agent_id=agent_id)
    for task in tasks:
        if task["task_name"] == task_name:
            events = await storage.get_recent_events(agent_id=agent_id, limit=50)
            return templates.TemplateResponse(
                "task_detail.html",
                {
                    "request": request,
                    "task": task,
                    "events": events,
                    "active": False,
                },
            )

    return templates.TemplateResponse(
        "404.html",
        {"request": request, "message": "Task not found"},
        status_code=404,
    )


# HTMX partial endpoints for live updates


@router.get("/partials/agents", response_class=HTMLResponse)
async def agents_partial(request: Request) -> HTMLResponse:
    """Partial view of agent list for HTMX updates."""
    agents = manager.get_connected_agents()
    return templates.TemplateResponse(
        "partials/agent_list.html",
        {"request": request, "agents": agents},
    )


@router.get("/partials/needs-attention", response_class=HTMLResponse)
async def needs_attention_partial(request: Request) -> HTMLResponse:
    """Partial view of agents needing attention for HTMX updates."""
    agents = manager.get_agents_needing_attention()
    return templates.TemplateResponse(
        "partials/needs_attention.html",
        {"request": request, "agents": agents},
    )


@router.get("/partials/agent/{agent_id}/task", response_class=HTMLResponse)
async def agent_task_partial(request: Request, agent_id: str) -> HTMLResponse:
    """Partial view of agent's current task for HTMX updates."""
    agent = manager.get_agent(agent_id)
    return templates.TemplateResponse(
        "partials/task_card.html",
        {"request": request, "agent": agent},
    )
