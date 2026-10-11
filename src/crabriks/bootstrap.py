"""Backward-compatible facade for crabriks.capabilities.bootstrap."""

from crabriks.capabilities.bootstrap import (
    BootstrapContext,
    BootstrapFile,
    load_bootstrap,
)

__all__ = ["BootstrapContext", "BootstrapFile", "load_bootstrap"]
