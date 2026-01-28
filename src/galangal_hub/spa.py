"""
SPA (Single Page Application) support for React frontend.

Serves the React build and handles client-side routing.
"""

from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from galangal_hub.auth import (
    SESSION_COOKIE,
    is_dashboard_auth_enabled,
    verify_session_token,
)

# Default frontend dist directory (built React app)
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


def get_spa_router(dist_dir: Path | None = None) -> APIRouter:
    """
    Create a router for serving the React SPA.

    Args:
        dist_dir: Path to the frontend dist directory. Defaults to
                  the built-in frontend/dist directory.

    Returns:
        FastAPI router configured for SPA serving.
    """
    router = APIRouter(tags=["spa"])

    dist_path = dist_dir or FRONTEND_DIST
    index_path = dist_path / "index.html"

    async def check_auth(request: Request) -> bool:
        """Check if user is authenticated."""
        if not is_dashboard_auth_enabled():
            return True
        session_token = request.cookies.get(SESSION_COOKIE)
        return session_token is not None and verify_session_token(session_token)

    @router.get("/", response_class=HTMLResponse)
    async def spa_root(request: Request) -> Response:
        """Serve the SPA index.html for the root route."""
        if not await check_auth(request):
            return RedirectResponse(url="/login", status_code=302)

        if not index_path.exists():
            return HTMLResponse(
                content="<h1>Frontend not built</h1><p>Run 'npm run build' in frontend/</p>",
                status_code=500,
            )
        return FileResponse(index_path, media_type="text/html")

    @router.get("/agents", response_class=HTMLResponse)
    @router.get("/agents/{agent_id:path}", response_class=HTMLResponse)
    @router.get("/tasks", response_class=HTMLResponse)
    @router.get("/tasks/{path:path}", response_class=HTMLResponse)
    async def spa_routes(request: Request) -> Response:
        """Serve the SPA index.html for client-side routes."""
        if not await check_auth(request):
            return RedirectResponse(url="/login", status_code=302)

        if not index_path.exists():
            return HTMLResponse(
                content="<h1>Frontend not built</h1><p>Run 'npm run build' in frontend/</p>",
                status_code=500,
            )
        return FileResponse(index_path, media_type="text/html")

    return router


def mount_spa_static(app, dist_dir: Path | None = None) -> None:
    """
    Mount the SPA static files (JS, CSS, assets).

    Args:
        app: FastAPI application instance.
        dist_dir: Path to the frontend dist directory.
    """
    dist_path = dist_dir or FRONTEND_DIST
    assets_path = dist_path / "assets"

    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="spa-assets")

    # Also serve favicon and other root-level static files
    for static_file in ["favicon.svg", "favicon.ico", "robots.txt"]:
        file_path = dist_path / static_file
        if file_path.exists():
            @app.get(f"/{static_file}", include_in_schema=False)
            async def serve_static(path: Path = file_path) -> FileResponse:
                return FileResponse(path)
