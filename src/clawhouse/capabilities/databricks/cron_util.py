"""Quartz cron utilities for Databricks Lakeflow Jobs scheduling."""

from __future__ import annotations

from databricks.sdk.service.jobs import CronSchedule, PauseStatus


def to_quartz_cron(cron: str) -> str:
    """Convert standard 5-field cron or preserve 6/7-field Quartz cron."""
    tokens = cron.strip().split()
    if len(tokens) in (6, 7):
        return cron.strip()
    if len(tokens) == 5:
        m, h, dom, mon, dow = tokens
        if dow == "*":
            dow = "?"
        elif dom == "*":
            dom = "?"
        return f"0 {m} {h} {dom} {mon} {dow}"
    return cron.strip()


def build_cron_schedule(
    cron_expression: str | None,
    timezone_id: str = "UTC",
    pause_status: str | None = "UNPAUSED",
) -> CronSchedule | None:
    """Build a Databricks Job CronSchedule from a cron expression."""
    if not cron_expression:
        return None
    quartz = to_quartz_cron(cron_expression)
    status = (
        PauseStatus.PAUSED
        if pause_status and pause_status.upper() == "PAUSED"
        else PauseStatus.UNPAUSED
    )
    return CronSchedule(
        quartz_cron_expression=quartz,
        timezone_id=timezone_id,
        pause_status=status,
    )
