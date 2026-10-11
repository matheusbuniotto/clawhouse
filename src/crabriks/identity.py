"""Backward-compatible facade for crabriks.api.identity."""

from crabriks.api.identity import Caller, Unauthenticated, resolve_caller

__all__ = ["Caller", "Unauthenticated", "resolve_caller"]
