"""Backward-compatible facade for clawhouse.capabilities.bootstrap."""

from clawhouse.capabilities.bootstrap import (
    BootstrapContext,
    BootstrapFile,
    load_bootstrap,
    load_bootstrap_directives,
)

__all__ = ["BootstrapContext", "BootstrapFile", "load_bootstrap", "load_bootstrap_directives"]
