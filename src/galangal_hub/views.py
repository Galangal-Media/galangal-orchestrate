"""
HTML views for the dashboard UI.

Uses Jinja2 templates with HTMX for interactivity.
"""

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from galangal_hub.auth import (
    SESSION_COOKIE,
    create_session_token,
    is_dashboard_auth_enabled,
    require_dashboard_auth,
    verify_dashboard_credentials,
    verify_session_token,
)
from galangal_hub.connection import manager
from galangal_hub.storage import storage

router = APIRouter(tags=["views"])

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


async def check_auth(request: Request) -> bool:
    """Check if user is authenticated."""
    if not is_dashboard_auth_enabled():
        return True
    session_token = request.cookies.get(SESSION_COOKIE)
    return session_token is not None and verify_session_token(session_token)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Login page."""
    # If already authenticated, redirect to dashboard
    if await check_auth(request):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    """Handle login form submission."""
    if verify_dashboard_credentials(username, password):
        # Create session and redirect to dashboard
        response = RedirectResponse(url="/", status_code=302)
        session_token = create_session_token()
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_token,
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,  # 7 days
        )
        return response
    else:
        # Invalid credentials
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Logout and clear session."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    """Main dashboard view."""
    if not await check_auth(request):
        return RedirectResponse(url="/login", status_code=302)

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
            "auth_enabled": is_dashboard_auth_enabled(),
        },
    )


@router.get("/agent/{agent_id}", response_class=HTMLResponse)
async def agent_detail(request: Request, agent_id: str) -> HTMLResponse | RedirectResponse:
    """Agent detail view."""
    if not await check_auth(request):
        return RedirectResponse(url="/login", status_code=302)

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
            "auth_enabled": is_dashboard_auth_enabled(),
        },
    )


@router.get("/task/{agent_id}/{task_name}", response_class=HTMLResponse)
async def task_detail(request: Request, agent_id: str, task_name: str) -> HTMLResponse | RedirectResponse:
    """Task detail view."""
    if not await check_auth(request):
        return RedirectResponse(url="/login", status_code=302)

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
                "auth_enabled": is_dashboard_auth_enabled(),
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
                    "auth_enabled": is_dashboard_auth_enabled(),
                },
            )

    return templates.TemplateResponse(
        "404.html",
        {"request": request, "message": "Task not found"},
        status_code=404,
    )


# HTMX partial endpoints for live updates


@router.get("/partials/agents", response_class=HTMLResponse)
async def agents_partial(request: Request) -> HTMLResponse | RedirectResponse:
    """Partial view of agent list for HTMX updates."""
    if not await check_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    agents = manager.get_connected_agents()
    return templates.TemplateResponse(
        "partials/agent_list.html",
        {"request": request, "agents": agents},
    )


@router.get("/partials/needs-attention", response_class=HTMLResponse)
async def needs_attention_partial(request: Request) -> HTMLResponse | RedirectResponse:
    """Partial view of agents needing attention for HTMX updates."""
    if not await check_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    agents = manager.get_agents_needing_attention()
    return templates.TemplateResponse(
        "partials/needs_attention.html",
        {"request": request, "agents": agents},
    )


@router.get("/partials/agent/{agent_id}/task", response_class=HTMLResponse)
async def agent_task_partial(request: Request, agent_id: str) -> HTMLResponse | RedirectResponse:
    """Partial view of agent's current task for HTMX updates."""
    if not await check_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    agent = manager.get_agent(agent_id)
    return templates.TemplateResponse(
        "partials/task_card.html",
        {"request": request, "agent": agent},
    )
