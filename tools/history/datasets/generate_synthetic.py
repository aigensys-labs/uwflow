"""Create an immutable, deterministic synthetic UWflow historical dataset."""

from __future__ import annotations

import argparse
from datetime import date
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

from uwflow_history.config import HistoryConfigurationError  # noqa: E402
from uwflow_history.factory import create_history_sink  # noqa: E402
from uwflow_history.generation.synthetic_portfolio import (  # noqa: E402
    build_manifest,
    default_dataset_id,
    generate_cases,
)


def main() -> int:
    """Generate a reproducible synthetic historical portfolio in the selected backend."""
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic underwriting portfolio and write it once"
    )
    parser.add_argument(
        "--count", type=int, default=50_000, help="Number of synthetic applications"
    )
    parser.add_argument("--seed", type=int, default=17, help="Deterministic random seed")
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--history-months", type=int, default=36)
    parser.add_argument("--dataset-id", help="Immutable dataset ID; defaults to a deterministic ID")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="Acknowledge the immutable dataset write (also requires UWFLOW_HISTORY_READ_ONLY=false)",
    )
    args = parser.parse_args()
    dataset_id = args.dataset_id or default_dataset_id(
        count=args.count, seed=args.seed, as_of_date=args.as_of_date
    )
    batch_size = args.batch_size or 1000
    try:
        sink = create_history_sink(allow_write=args.allow_write)
        manifest = build_manifest(
            dataset_id=dataset_id,
            count=args.count,
            seed=args.seed,
            as_of_date=args.as_of_date,
            history_months=args.history_months,
        )
        stored = sink.write_dataset(
            manifest,
            generate_cases(
                count=args.count,
                seed=args.seed,
                as_of_date=args.as_of_date,
                history_months=args.history_months,
            ),
            batch_size=batch_size,
        )
    except (HistoryConfigurationError, OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    finally:
        close = getattr(locals().get("sink"), "close", None)
        if callable(close):
            close()
    print(f"Created immutable dataset: {stored.dataset_id}")
    print(f"Cases: {stored.case_count:,}")
    print(f"Connector: {__import__('os').getenv('UWFLOW_HISTORY_CONNECTOR', 'postgres')}")
    print(f"Content SHA-256: {stored.data_sha256}")
    print(
        "Target: FSTPD30 = 1 when any of the first three scheduled instalments reaches 30+ DPD; 0 otherwise."
    )
    print("Maturity: four months on book; immature cases retain a null FSTPD30 label.")
    print(
        "Risk features: correlated synthetic bureau history, affordability and ten alternative-data source fixtures."
    )
    print(
        "Synthetic only; FSTPD30 is counterfactual and illustrative, not observed booked-loan performance or calibrated PD."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
