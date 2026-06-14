"""Hermes plugin package root for Hermes Loom.

Hermes loads this when the repo is installed at ``$HERMES_HOME/plugins/<name>/``.
It re-exports ``register(ctx)`` from the ``hermes_loom`` package. The sys.path
fallback makes the import work regardless of the synthetic module name Hermes
assigns to a hyphenated plugin directory.
"""

from __future__ import annotations

try:  # normal case: loaded as a package, hermes_loom is a subpackage
    from .hermes_loom.plugin import register
except Exception:  # pragma: no cover - odd loader/naming: import by path
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from hermes_loom.plugin import register  # type: ignore

__all__ = ["register"]
