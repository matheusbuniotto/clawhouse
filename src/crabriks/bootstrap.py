"""Backward-compatible facade for crabriks.capabilities.bootstrap."""

from crabriks.capabilities.bootstrap import (
    BootstrapContext,
    BootstrapFile,
    load_bootstrap,
    load_bootstrap_directives,
)

__all__ = ["BootstrapContext", "BootstrapFile", "load_bootstrap", "load_bootstrap_directives"]
