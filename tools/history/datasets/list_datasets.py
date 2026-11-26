"""List datasets available through the configured historical-data connector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _history_package_root() -> Path:
    """Return the import root for source and immutable Namespace Files layouts.

    Source checkouts keep ``uwflow_history`` under ``modules/history/python``. The history-tools
    bundle deliberately maps it to ``scripts/uwflow_history`` to preserve the
    existing Kestra artifact path contract.
    """
    for candidate in Path(__file__).resolve().parents:
        source_package = candidate / "modules" / "history" / "python" / "uwflow_history"
        if (source_package / "__init__.py").is_file():
            return source_package.parent
        bundled_scripts = candidate / "scripts"
        if (bundled_scripts / "uwflow_history" / "__init__.py").is_file():
            return bundled_scripts
    raise RuntimeError(
        "Cannot locate uwflow_history in the source tree or scripts/ Namespace Files layout"
    )


ROOT = _history_package_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uwflow_history.factory import create_history_source  # noqa: E402


def main() -> int:
    """List the historical datasets available through the configured connector."""
    parser = argparse.ArgumentParser(description="List UWflow historical datasets")
    args = parser.parse_args()
    source = create_history_source()
    try:
        manifests = source.list_datasets()
        print(json.dumps([item.to_dict() for item in manifests], indent=2, ensure_ascii=False))
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
