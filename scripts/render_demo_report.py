"""Run a synthetic application locally and generate its decision reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from demo_run import DEFAULT_APPLICATION, run
from report_renderer import generate_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UWflow synthetic underwriting HTML and PDF reports")
    parser.add_argument("--input", type=Path, help="Application JSON file; defaults to the John Jones demo")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "generated_reports", help="Directory for JSON, HTML and PDF outputs")
    parser.add_argument("--applicant-id", help="Override applicant ID (changes deterministic synthetic provider responses)")
    args = parser.parse_args()

    application = DEFAULT_APPLICATION.copy()
    if args.input:
        application.update(json.loads(args.input.read_text(encoding="utf-8")))
    if args.applicant_id:
        application["applicant_id"] = args.applicant_id

    decision = run(application)
    reports = generate_reports(decision, args.output_dir)

    print(f"Decision: {decision['decision']}")
    print(f"Reference: {decision['decision_reference']}")
    for kind, path in reports.items():
        print(f"{kind.upper()}: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
