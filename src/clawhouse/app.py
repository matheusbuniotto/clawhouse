"""Backward-compatible entry point for databricks.yml and external runners."""

from clawhouse.api.app import app, create_app

__all__ = ["app", "create_app"]
