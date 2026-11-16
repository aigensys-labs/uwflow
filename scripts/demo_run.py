"""Run the full synthetic UWflow journey locally, without Kestra."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from aidflow_scoring import score_customer_profile
from alternative_data import SOURCE_IDS, get_alternative_data
from bureau_client import get_bureau_data
from hard_gates import evaluate_hard_gates
from uwflow_engine import run_uwflow_decision

DEFAULT_APPLICATION = {
    "applicant_id": "APP-2026-9482",
    "applicant_name": "John Jones",
    "applicant_age": 34,
    "monthly_income": 1966.61,
    "requested_amount": 8194.20,
    "employment_status": "FULL_TIME",
    "existing_monthly_debt_payments": 266.31,
    "monthly_housing_cost": 491.65,
    "loan_term_months": 60,
    "data_sharing_consent": True,
    "currency": "EUR",
}


def run(application: dict) -> dict:
    gates = evaluate_hard_gates(application)
    bureau = get_bureau_data(
        application["applicant_id"],
        application.get("existing_monthly_debt_payments", 0.0),
        gates,
    )
    source_results = []
    if gates["passed"] and bureau.get("decision_status") != "DECLINE" and application.get("data_sharing_consent", False):
        source_results = [get_alternative_data(source_id, application["applicant_id"], application) for source_id in SOURCE_IDS]

    # The dedicated AIDflow step returns one complex customer-profile score.
    aidflow_result = score_customer_profile(source_results)

    # UWflow owns bureau/hard-gate policy, affordability, pricing and decision.
    return run_uwflow_decision(application, gates, bureau, aidflow_result, source_results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic UWflow underwriting demo")
    parser.add_argument("--input", type=Path, help="Path to an application JSON file")
    parser.add_argument("--applicant-id", help="Override the sample applicant ID")
    args = parser.parse_args()

    application = DEFAULT_APPLICATION.copy()
    if args.input:
        application.update(json.loads(args.input.read_text(encoding="utf-8")))
    if args.applicant_id:
        application["applicant_id"] = args.applicant_id

    print(json.dumps(run(application), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
