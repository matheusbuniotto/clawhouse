"""Static file serving and SPA shell routes for the Lovable (TanStack) UI bundle."""

import mimetypes
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller

STATIC = Path(__file__).resolve().parent.parent.parent / "static"
SHELL = STATIC / "index.html"

_PAGE_PATHS = (
    "/",
    "/chat",
    "/sessions",
    "/agents",
    "/new",
    "/approvals",
    "/status",
    "/jobs",
)

_MIME: dict[str, str] = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".ico": "image/x-icon",
    ".txt": "text/plain",
}


def _media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _MIME:
        return _MIME[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _safe_file(relative: str) -> Path | None:
    base = STATIC.resolve()
    candidate = (STATIC / relative).resolve()
    if not str(candidate).startswith(str(base)):
        return None
    return candidate if candidate.is_file() else None


def _cache_headers(app: FastAPI) -> None:
    """Revalidate on every load so redeploys reach browsers holding stale assets."""

    @app.middleware("http")
    async def disable_http_cache(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if "cache-control" not in response.headers:
            response.headers["cache-control"] = "no-cache"
        return response


def _page_routes(app: FastAPI) -> None:
    for path in _PAGE_PATHS:

        @app.get(path)
        async def shell_page(caller: Caller = _require_caller) -> FileResponse:
            del caller
            if not SHELL.is_file():
                raise HTTPException(
                    status_code=503,
                    detail="UI bundle missing; run scripts/sync-lovable-static.sh",
                )
            return FileResponse(SHELL, media_type="text/html")


def _asset_routes(app: FastAPI) -> None:
    @app.get("/assets/{asset_path:path}")
    async def spa_asset(asset_path: str) -> FileResponse:
        file = _safe_file(f"assets/{asset_path}")
        if file is None:
            raise HTTPException(status_code=404)
        return FileResponse(file, media_type=_media_type(file))

    @app.get("/favicon.ico")
    async def favicon() -> FileResponse:
        file = _safe_file("favicon.ico")
        if file is None:
            raise HTTPException(status_code=404)
        return FileResponse(file, media_type=_media_type(file))

    @app.get("/robots.txt")
    async def robots() -> FileResponse:
        file = _safe_file("robots.txt")
        if file is None:
            raise HTTPException(status_code=404)
        return FileResponse(file, media_type=_media_type(file))


def register_assets(app: FastAPI) -> None:
    _cache_headers(app)
    _page_routes(app)
    _asset_routes(app)
