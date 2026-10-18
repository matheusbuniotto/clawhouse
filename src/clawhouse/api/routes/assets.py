"""Static file serving and shell HTML routes."""

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller

STATIC = Path(__file__).resolve().parent.parent.parent / "static"


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
    @app.get("/")
    @app.get("/chat")
    @app.get("/sessions")
    @app.get("/agents")
    @app.get("/new")
    @app.get("/approvals")
    @app.get("/status")
    @app.get("/jobs")
    async def shell_page(caller: Caller = _require_caller) -> FileResponse:
        del caller
        return FileResponse(STATIC / "index.html")


def _asset_routes(app: FastAPI) -> None:
    _style_routes(app)
    _script_routes(app)


def _style_routes(app: FastAPI) -> None:
    @app.get("/tokens.css")
    async def tokens_style() -> FileResponse:
        return FileResponse(STATIC / "tokens.css", media_type="text/css")

    @app.get("/shell.css")
    async def shell_style() -> FileResponse:
        return FileResponse(STATIC / "shell.css", media_type="text/css")

    @app.get("/transcript.css")
    async def transcript_style() -> FileResponse:
        return FileResponse(STATIC / "transcript.css", media_type="text/css")

    @app.get("/screens.css")
    async def screens_style() -> FileResponse:
        return FileResponse(STATIC / "screens.css", media_type="text/css")


def _script_routes(app: FastAPI) -> None:
    _core_script_routes(app)
    _screen_script_routes(app)


def _core_script_routes(app: FastAPI) -> None:
    @app.get("/boot.js")
    async def boot_script() -> FileResponse:
        return FileResponse(STATIC / "boot.js", media_type="text/javascript")

    @app.get("/shell.js")
    async def shell_script() -> FileResponse:
        return FileResponse(STATIC / "shell.js", media_type="text/javascript")

    @app.get("/dom.js")
    async def dom_script() -> FileResponse:
        return FileResponse(STATIC / "dom.js", media_type="text/javascript")

    @app.get("/transcript.js")
    async def transcript_script() -> FileResponse:
        return FileResponse(STATIC / "transcript.js", media_type="text/javascript")

    @app.get("/highlight.js")
    async def highlight_script() -> FileResponse:
        return FileResponse(STATIC / "highlight.js", media_type="text/javascript")

    @app.get("/jobs.js")
    async def jobs_script() -> FileResponse:
        return FileResponse(STATIC / "jobs.js", media_type="text/javascript")

    @app.get("/cards.js")
    async def cards_script() -> FileResponse:
        return FileResponse(STATIC / "cards.js", media_type="text/javascript")

    @app.get("/mentions.js")
    async def mentions_script() -> FileResponse:
        return FileResponse(STATIC / "mentions.js", media_type="text/javascript")


def _screen_script_routes(app: FastAPI) -> None:
    @app.get("/agents.js")
    async def agents_page_script() -> FileResponse:
        return FileResponse(STATIC / "agents.js", media_type="text/javascript")

    @app.get("/jobspage.js")
    async def jobs_page_script() -> FileResponse:
        return FileResponse(STATIC / "jobspage.js", media_type="text/javascript")

    @app.get("/chat.js")
    async def chat_script() -> FileResponse:
        return FileResponse(STATIC / "chat.js", media_type="text/javascript")

    @app.get("/sessions.js")
    async def sessions_script() -> FileResponse:
        return FileResponse(STATIC / "sessions.js", media_type="text/javascript")

    @app.get("/new.js")
    async def new_script() -> FileResponse:
        return FileResponse(STATIC / "new.js", media_type="text/javascript")

    @app.get("/approvals.js")
    async def approvals_script() -> FileResponse:
        return FileResponse(STATIC / "approvals.js", media_type="text/javascript")

    @app.get("/status.js")
    async def status_script() -> FileResponse:
        return FileResponse(STATIC / "status.js", media_type="text/javascript")
