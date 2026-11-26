"""Standalone seven-stage UWflow Core command-line runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.python.runner import DEFAULT_APPLICATION, run

DEFAULT_OUTPUT_DIR = Path.cwd() / "var/reports"


def _load_application(path: Path | None, applicant_id: str | None) -> dict[str, Any]:
    application = DEFAULT_APPLICATION.copy()
    if path is not None:
        try:
            supplied = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load application JSON from {path}: {exc}") from exc
        if not isinstance(supplied, dict):
            raise ValueError("Application input must be a JSON object.")
        application.update(supplied)
    if applicant_id:
        application["applicant_id"] = applicant_id
    return application


def main() -> int:
    """Run the complete seven-stage Core workflow and render applicant reports."""
    parser = argparse.ArgumentParser(
        description="Run all seven UWflow Core stages locally without Kestra."
    )
    parser.add_argument(
        "--input", type=Path, help="Application JSON file; defaults to the reference case"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--applicant-id", help="Override applicant ID for deterministic synthetic responses"
    )
    args = parser.parse_args()

    try:
        application = _load_application(args.input, args.applicant_id)
        # Stages 1-6: the same Core decision logic used by the Kestra tasks.
        decision = run(application)
        # Stage 7: presentation only; this does not recalculate the decision.
        from report_renderer import generate_reports

        reports = generate_reports(decision, args.output_dir)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"UWflow Core failed: {exc}\n")

    print(f"Decision: {decision['decision']}")
    print(f"Reference: {decision['decision_reference']}")
    print("Stages completed: 7/7")
    for kind, path in reports.items():
        print(f"{kind.upper()}: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
