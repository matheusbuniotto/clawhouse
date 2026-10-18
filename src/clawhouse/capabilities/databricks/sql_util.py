"""SQL analysis and validation helpers for Databricks execution."""

from __future__ import annotations

import re

_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n]*|\/\*[\s\S]*?\*\/)")
_MUTATING_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "drop",
    "create",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "optimize",
    "vacuum",
}
_READONLY_KEYWORDS = {"select", "show", "describe", "desc", "explain"}


def strip_sql_comments(sql: str) -> str:
    return _SQL_COMMENT_PATTERN.sub(" ", sql).strip()


def is_readonly_query(sql: str) -> bool:
    cleaned = strip_sql_comments(sql)
    tokens = [t.lower() for t in re.split(r"\s+", cleaned) if t]
    if not tokens or tokens[0] in _MUTATING_KEYWORDS:
        return False

    first_word = tokens[0]
    if first_word == "with":
        has_mutation = any(t in _MUTATING_KEYWORDS for t in tokens)
        return not has_mutation and ("select" in tokens)

    return first_word in _READONLY_KEYWORDS


def enforce_query_limit(sql: str, default_limit: int = 100) -> str:
    if not is_readonly_query(sql):
        return sql
    if re.search(r"\blimit\s+\d+", sql, re.IGNORECASE):
        return sql
    return f"{sql.strip()}\nLIMIT {default_limit}"


def build_agentic_query(
    query: str,
    *,
    agent_name: str = "Agent",
    instructions: str | None = None,
    endpoint: str = "databricks-meta-llama-3-3-70b-instruct",
    sample_limit: int = 100,
) -> str:
    """Wrap a SQL query into an agentic DBSQL query using ai_query."""
    cleaned = strip_sql_comments(query).strip().rstrip(";")
    agent_clean = agent_name.lstrip("@").strip()
    prompt = f"You are @{agent_clean}."
    if instructions:
        prompt += f" {instructions.strip()}"
    else:
        prompt += " Analyze these query results and provide key insights, anomalies, and metrics."
    escaped = prompt.replace("'", "''")
    return (
        f"WITH source_query AS (\n"
        f"  {cleaned}\n"
        f"),\n"
        f"sample_data AS (\n"
        f"  SELECT * FROM source_query LIMIT {sample_limit}\n"
        f"),\n"
        f"encoded_summary AS (\n"
        f"  SELECT to_json(collect_list(struct(*))) AS data_json\n"
        f"  FROM sample_data\n"
        f")\n"
        f"SELECT ai_query(\n"
        f"  '{endpoint}',\n"
        f"  '{escaped}\\n\\nQuery Results:\\n' || data_json\n"
        f") AS agent_analysis\n"
        f"FROM encoded_summary"
    )
