"""Memory CRUD and search routes."""

from fastapi import FastAPI, HTTPException, Request

from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller
from clawhouse.store.shapes import MemoryEntry
from clawhouse.store.store import SessionForbidden, SessionNotFound


def _memory_out(row: MemoryEntry) -> dict[str, object]:
    return {
        "id": row.id,
        "text": row.text,
        "table_fqn": row.table_fqn,
        "source_session_id": row.source_session_id,
        "created_at": row.created_at.isoformat(),
    }


def _memory_search_routes(app: FastAPI) -> None:
    @app.get("/api/search")
    async def search_transcripts(
        request: Request,
        q: str = "",
        limit: int = 20,
        caller: Caller = _require_caller,
    ) -> dict[str, object]:
        if not q.strip():
            raise HTTPException(status_code=422, detail="q is required")
        hits = await request.app.state.store.search_transcripts(caller.user_id, q, limit)
        return {
            "results": [
                {
                    "session_id": hit.session_id,
                    "role": hit.role,
                    "excerpt": hit.excerpt,
                    "created_at": hit.created_at.isoformat(),
                }
                for hit in hits
            ]
        }


def _memory_crud_routes(app: FastAPI) -> None:
    @app.get("/api/memory")
    async def list_memory(
        request: Request,
        limit: int = 20,
        caller: Caller = _require_caller,
    ) -> dict[str, object]:
        rows = await request.app.state.store.list_memories(caller.user_id, limit)
        return {"entries": [_memory_out(row) for row in rows]}

    @app.post("/api/memory", status_code=201)
    async def create_memory(
        request: Request,
        caller: Caller = _require_caller,
    ) -> dict[str, object]:
        body = await request.json()
        text = str(body.get("text", ""))
        if not text.strip():
            raise HTTPException(status_code=422, detail="text is required")
        source = body.get("source_session_id")
        table_fqn = body.get("table_fqn")
        try:
            entry = await request.app.state.store.save_memory(
                caller.user_id,
                text,
                str(source) if source else None,
                str(table_fqn) if table_fqn else None,
            )
        except (SessionNotFound, SessionForbidden) as exc:
            raise HTTPException(status_code=404, detail="Session not found.") from exc
        return {"id": entry.id, "text": entry.text, "created_at": entry.created_at.isoformat()}

    @app.delete("/api/memory/{memory_id}", status_code=204)
    async def delete_memory(
        memory_id: str,
        request: Request,
        caller: Caller = _require_caller,
    ) -> None:
        deleted = await request.app.state.store.delete_memory(caller.user_id, memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found.")


def _memory_routes(app: FastAPI) -> None:
    _memory_search_routes(app)
    _memory_crud_routes(app)
