"""Composer slash commands and mention suggestions routes."""

from collections.abc import Sequence

from fastapi import FastAPI, Query

from clawhouse.api.identity import Caller
from clawhouse.api.routes.sessions import _require_caller


def _static_command_suggestions() -> list[dict[str, str]]:
    return [
        {
            "id": "/compact",
            "label": "/compact",
            "description": "Compact conversation history using context compaction",
        },
        {
            "id": "/schedule",
            "label": "/schedule",
            "description": 'Schedule recurring turn: /schedule cron "..." or every <N>m',
        },
        {"id": "/clear", "label": "/clear", "description": "Start a fresh conversation"},
        {"id": "/help", "label": "/help", "description": "Show available shortcuts and commands"},
    ]


def _discover_skill_suggestions(workspace: object) -> list[dict[str, str]]:
    skills: list[dict[str, str]] = []
    skills_dir = getattr(workspace, "skills", None)
    if skills_dir and skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                s_name = skill_dir.name
                skills.append(
                    {
                        "id": f"/skill:{s_name}",
                        "label": f"/skill:{s_name}",
                        "description": f"Activate {s_name} skill instructions",
                    }
                )
    return skills


def _slash_suggestions(app: FastAPI, q: str) -> dict[str, object]:
    query = q.lower().strip()
    commands = _static_command_suggestions()
    filtered_cmds = [
        c
        for c in commands
        if not query or query in c["id"].lower() or query in c["description"].lower()
    ]
    skills = _discover_skill_suggestions(getattr(app.state, "workspace", None))
    filtered_skills = [
        s
        for s in skills
        if not query or query in s["id"].lower() or query in s["description"].lower()
    ]
    return {"commands": filtered_cmds, "skills": filtered_skills}


def _flatten_slash_suggestions(res: dict[str, object]) -> list[dict[str, str]]:
    raw_skills = res.get("skills", [])
    skills_list: Sequence[dict[str, str]] = raw_skills if isinstance(raw_skills, list) else []
    raw_cmds = res.get("commands", [])
    cmds_list: Sequence[dict[str, str]] = raw_cmds if isinstance(raw_cmds, list) else []
    return [
        {
            "label": s["label"],
            "insert_text": s["id"],
            "detail": s["description"],
            "kind": "skill",
        }
        for s in skills_list
    ] + [
        {
            "label": c["label"],
            "insert_text": c["id"],
            "detail": c["description"],
            "kind": "command",
        }
        for c in cmds_list
    ]


async def _at_suggestions(app: FastAPI, caller: Caller, q: str) -> dict[str, object]:
    query = q.lower().strip()
    agents_list: list[dict[str, str]] = [
        {"name": "main", "description": "Platform agent", "emoji": "🦀"}
    ]
    custom = await app.state.store.list_custom_agents(caller.user_id)
    for ca in custom:
        agents_list.append(
            {"name": ca.name, "description": ca.description, "emoji": ca.signature_emoji}
        )
    filtered_agents = [
        a
        for a in agents_list
        if not query or query in a["name"].lower() or query in a["description"].lower()
    ]
    files_list = [
        {"path": "AGENTS.md", "label": "AGENTS.md"},
        {"path": "SOUL.md", "label": "SOUL.md"},
        {"path": "IDENTITY.md", "label": "IDENTITY.md"},
        {"path": "USER.md", "label": "USER.md"},
        {"path": "MEMORY.md", "label": "MEMORY.md"},
    ]
    filtered_files = [f for f in files_list if not query or query in f["path"].lower()]
    tables_list = [
        {"name": "samples.nyctaxi.trips", "description": "NYC Taxi trips sample data"},
        {"name": "main.default.customers", "description": "Customer accounts table"},
        {"name": "main.default.orders", "description": "Order records table"},
    ]
    filtered_tables = [
        t
        for t in tables_list
        if not query or query in t["name"].lower() or query in t["description"].lower()
    ]
    return {
        "agents": filtered_agents,
        "files": filtered_files,
        "tables": filtered_tables,
    }


def _flatten_at_suggestions(res: dict[str, object]) -> list[dict[str, str]]:
    raw_agents = res.get("agents", [])
    agents: Sequence[dict[str, str]] = raw_agents if isinstance(raw_agents, list) else []
    raw_files = res.get("files", [])
    files: Sequence[dict[str, str]] = raw_files if isinstance(raw_files, list) else []
    raw_tables = res.get("tables", [])
    tables: Sequence[dict[str, str]] = raw_tables if isinstance(raw_tables, list) else []
    return (
        [
            {
                "label": a["name"],
                "insert_text": f"@{a['name']}",
                "detail": a["description"],
                "kind": "agent",
            }
            for a in agents
        ]
        + [
            {
                "label": f["label"],
                "insert_text": f"@{f['path']}",
                "detail": "file",
                "kind": "file",
            }
            for f in files
        ]
        + [
            {
                "label": t["name"],
                "insert_text": f"@{t['name']}",
                "detail": t["description"],
                "kind": "table",
            }
            for t in tables
        ]
    )


def _composer_routes(app: FastAPI) -> None:
    @app.get("/api/composer/suggestions")
    async def composer_suggestions(
        *,
        prefix: str | None = None,
        trigger_type: str | None = Query(None, alias="type"),
        q: str | None = None,
        query: str | None = None,
        caller: Caller = _require_caller,
    ) -> dict[str, object]:
        p = trigger_type if trigger_type is not None else (prefix or "@")
        search_query = query if query is not None else (q or "")
        if p == "/":
            slash_res = _slash_suggestions(app, search_query)
            slash_res["suggestions"] = _flatten_slash_suggestions(slash_res)
            return slash_res

        at_res = await _at_suggestions(app, caller, search_query)
        at_res["suggestions"] = _flatten_at_suggestions(at_res)
        return at_res
