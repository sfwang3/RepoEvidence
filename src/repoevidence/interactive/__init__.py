"""Lazy entry points for the persistent interactive workspace.

The module deliberately does not import Textual at package import time.  The
one-shot CLI and machine-facing commands can therefore remain independent of
the full-screen runtime.
"""

from __future__ import annotations

from typing import Any


def run_workspace(*args: Any, **kwargs: Any) -> int:
    """Run the Textual workspace after the caller has selected interactive mode."""

    from repoevidence.interactive.app import run_workspace as _run_workspace

    return _run_workspace(*args, **kwargs)


__all__ = ["run_workspace"]
