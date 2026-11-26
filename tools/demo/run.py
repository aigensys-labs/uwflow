"""Compatibility entry point for the Core seven-stage Python runner."""

from __future__ import annotations

from core.python.cli import main
from core.python.runner import DEFAULT_APPLICATION, run

__all__ = ["DEFAULT_APPLICATION", "run", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
