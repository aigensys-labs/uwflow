"""Execute the Core underwriting stages locally without Kestra.

The sequence mirrors the seven-stage Kestra reference flow for stages 1-6.
Stage 7 report generation is handled by :mod:`core.python.cli` so the same
engine result can be consumed by other applications without forcing file I/O.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "core" / "python" / "runtime"
for source_path in (PROJECT_ROOT, RUNTIME_ROOT):
    if source_path.is_dir() and str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

from aidflow_scoring import score_customer_profile
from alternative_data import get_alternative_data
from bureau_client import get_bureau_data
from hard_gates import evaluate_hard_gates
from policy_generated import build_stage3_source_plan
from uwflow_engine import run_uwflow_decision

DEFAULT_APPLICATION: dict[str, Any] = {
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


def run(application: dict[str, Any]) -> dict[str, Any]:
    """Run Core underwriting decision logic through Stage 6 and return its result."""
    gates = evaluate_hard_gates(application)
    bureau = get_bureau_data(
        application["applicant_id"],
        application.get("existing_monthly_debt_payments", 0.0),
        gates,
    )
    source_plan = build_stage3_source_plan(
        {
            "hard_gates_passed": bool(gates.get("passed", False)),
            "bureau_decision_status": str(bureau.get("decision_status", "")),
            "data_sharing_consent": bool(application.get("data_sharing_consent", False)),
        }
    )
    source_results = [
        get_alternative_data(source_id, application["applicant_id"], application)
        for source_id in source_plan["source_ids"]
    ]

    # Stage 5: AIDflow returns a profile inference result; it never makes the decision.
    aidflow_result = score_customer_profile(source_results)

    # Stage 6: UWflow owns policy, affordability, pricing and the final outcome.
    return run_uwflow_decision(application, gates, bureau, aidflow_result, source_results)
