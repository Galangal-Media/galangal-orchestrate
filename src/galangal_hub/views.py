"""
Authentication views for the dashboard UI.

Uses Jinja2 templates for the login page only.
The rest of the UI is served by the React SPA.
"""

from pathlib import Path

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from galangal_hub.auth import (
    SESSION_COOKIE,
    create_session_token,
    is_dashboard_auth_enabled,
    verify_dashboard_credentials,
    verify_session_token,
)

login_router = APIRouter(tags=["auth"])

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


async def check_auth(request: Request) -> bool:
    """Check if user is authenticated."""
    if not is_dashboard_auth_enabled():
        return True
    session_token = request.cookies.get(SESSION_COOKIE)
    return session_token is not None and verify_session_token(session_token)


@login_router.get("/login", response_model=None)
async def login_page(request: Request) -> Response:
    """Login page."""
    # If already authenticated, redirect to dashboard
    if await check_auth(request):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@login_router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
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


@login_router.get("/logout", response_model=None)
async def logout(request: Request) -> Response:
    """Logout and clear session."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


@login_router.get("/api/auth/status")
async def auth_status(request: Request) -> dict:
    """Check authentication status for the SPA."""
    authenticated = await check_auth(request)
    return {
        "authenticated": authenticated,
        "auth_required": is_dashboard_auth_enabled(),
    }
