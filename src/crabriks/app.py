"""Backward-compatible entry point for databricks.yml and external runners."""

from crabriks.api.app import app, create_app

__all__ = ["app", "create_app"]
