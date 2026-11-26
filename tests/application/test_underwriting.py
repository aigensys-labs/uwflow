"""Tests for the seven-stage Core underwriting decisions and policy boundaries."""

from __future__ import annotations

import unittest


from aidflow_scoring import PROFILE_INPUT_WEIGHTS, score_customer_profile
from alternative_data import SOURCE_IDS, get_alternative_data
from bureau_client import get_bureau_data
from tools.demo.run import DEFAULT_APPLICATION, run
from hard_gates import evaluate_hard_gates
from uwflow_engine import run_uwflow_decision
from policy_generated import build_stage3_source_plan

BASE_APPLICATION = DEFAULT_APPLICATION.copy()


def build_sources(application, gates, bureau):
    plan = build_stage3_source_plan(
        {
            "hard_gates_passed": bool(gates.get("passed", False)),
            "bureau_decision_status": str(bureau.get("decision_status", "")),
            "data_sharing_consent": bool(application.get("data_sharing_consent", False)),
        }
    )
    return [
        get_alternative_data(source_id, application["applicant_id"], application)
        for source_id in plan["source_ids"]
    ]


class UnderwritingDemoTests(unittest.TestCase):
    def test_default_application_passes_hard_gates(self):
        result = evaluate_hard_gates(BASE_APPLICATION)
        self.assertTrue(result["passed"], result["reason_codes"])

    def test_aidflow_consumes_all_ten_normalized_scores(self):
        sources = [
            get_alternative_data(s, BASE_APPLICATION["applicant_id"], BASE_APPLICATION)
            for s in SOURCE_IDS
        ]
        result = score_customer_profile(sources)
        self.assertEqual(result["scoring_status"], "SCORED")
        self.assertEqual(result["input_score_count"], 10)
        self.assertEqual(len(result["input_scores"]), 10)
        self.assertIsInstance(result["complex_customer_profile_score"], int)
        self.assertAlmostEqual(sum(PROFILE_INPUT_WEIGHTS.values()), 1.0)
        self.assertEqual(result["engine"], "AIDflow Scoring & Inference Engine")
        self.assertNotIn("decision", result)
        self.assertNotIn("approved_amount", result)

    def test_aidflow_requires_all_ten_inputs_without_imputation(self):
        sources = [
            get_alternative_data(s, BASE_APPLICATION["applicant_id"], BASE_APPLICATION)
            for s in SOURCE_IDS[:-1]
        ]
        result = score_customer_profile(sources)
        self.assertEqual(result["scoring_status"], "INCOMPLETE")
        self.assertIsNone(result["complex_customer_profile_score"])
        self.assertEqual(result["missing_source_ids"], ["merchant_affinity"])

    def test_aidflow_uses_all_ten_source_scores(self):
        sources = [
            get_alternative_data(s, BASE_APPLICATION["applicant_id"], BASE_APPLICATION)
            for s in SOURCE_IDS
        ]
        baseline = score_customer_profile(sources)["complex_customer_profile_score"]
        changed = [dict(row) for row in sources]
        changed[0]["profile_input_score"] = 0.0
        changed_score = score_customer_profile(changed)["complex_customer_profile_score"]
        self.assertNotEqual(baseline, changed_score)

    def test_default_application_completes_uwflow_decision(self):
        result = run(BASE_APPLICATION.copy())
        self.assertIn(result["decision"], {"APPROVED", "COUNTEROFFER", "REFER"})
        self.assertEqual(result["engine"], "UWflow Underwriting Engine")
        self.assertIsNotNone(result["complex_customer_profile_score"])
        self.assertEqual(result["aidflow_scoring"]["input_score_count"], 10)
        self.assertEqual(len(result["source_results"]), 10)

    def test_5000_eur_monthly_income_completes_underwriting(self):
        application = {**BASE_APPLICATION, "monthly_income": 5000.0}
        result = run(application)
        self.assertTrue(result["hard_gates"]["passed"])
        self.assertEqual(result["currency"], "EUR")
        self.assertEqual(result["aidflow_scoring"]["input_score_count"], 10)

    def test_czk_currency_is_rejected_by_eur_demo(self):
        application = {**BASE_APPLICATION, "currency": "CZK"}
        result = run(application)
        self.assertEqual(result["decision"], "DECLINED")
        self.assertIn("INVALID_APPLICATION_DATA", result["reason_codes"])

    def test_unemployed_applicant_fails_hard_gate(self):
        application = {**BASE_APPLICATION, "employment_status": "UNEMPLOYED"}
        result = run(application)
        self.assertEqual(result["decision"], "DECLINED")
        self.assertIn("UNEMPLOYED_STATUS", result["reason_codes"])

    def test_hard_gate_failure_stops_bureau_and_scoring(self):
        application = {**BASE_APPLICATION, "applicant_age": 17}
        gates = evaluate_hard_gates(application)
        bureau = get_bureau_data(
            application["applicant_id"], application["existing_monthly_debt_payments"], gates
        )
        aidflow = score_customer_profile([])
        result = run_uwflow_decision(application, gates, bureau, aidflow, [])
        self.assertEqual(bureau["status"], "SKIPPED")
        self.assertEqual(result["decision"], "DECLINED")
        self.assertEqual(result["risk_tier"], "NOT_SCORED")

    def test_bureau_response_is_deterministic(self):
        gates = evaluate_hard_gates(BASE_APPLICATION)
        first = get_bureau_data(
            BASE_APPLICATION["applicant_id"],
            BASE_APPLICATION["existing_monthly_debt_payments"],
            gates,
        )
        second = get_bureau_data(
            BASE_APPLICATION["applicant_id"],
            BASE_APPLICATION["existing_monthly_debt_payments"],
            gates,
        )
        self.assertEqual(first["bureau_score"], second["bureau_score"])
        self.assertEqual(first["decision_status"], second["decision_status"])

    def test_all_ten_source_connectors_return_profile_scores(self):
        records = [
            get_alternative_data(s, BASE_APPLICATION["applicant_id"], BASE_APPLICATION)
            for s in SOURCE_IDS
        ]
        self.assertEqual(len(records), 10)
        self.assertTrue(all(record["status"] == "SUCCESS" for record in records))
        self.assertTrue(all(0 <= record["profile_input_score"] <= 100 for record in records))

    def test_no_consent_does_not_allow_automated_approval(self):
        application = {**BASE_APPLICATION, "data_sharing_consent": False}
        gates = evaluate_hard_gates(application)
        bureau = get_bureau_data(
            application["applicant_id"], application["existing_monthly_debt_payments"], gates
        )
        aidflow = score_customer_profile([])
        result = run_uwflow_decision(application, gates, bureau, aidflow, [])
        self.assertEqual(result["decision"], "REFER")
        self.assertEqual(result["aidflow_scoring"]["scoring_status"], "INCOMPLETE")

    def test_bureau_decline_prevents_alternative_data_collection(self):
        application = {**BASE_APPLICATION, "applicant_id": "APP-DEMO-0208"}
        gates = evaluate_hard_gates(application)
        bureau = get_bureau_data(
            application["applicant_id"], application["existing_monthly_debt_payments"], gates
        )
        self.assertEqual(bureau["decision_status"], "DECLINE")
        self.assertEqual(build_sources(application, gates, bureau), [])

    def test_counteroffer_scenario(self):
        application = {**BASE_APPLICATION, "requested_amount": 36873.90}
        result = run(application)
        self.assertIn(result["decision"], {"COUNTEROFFER", "REFER"})
        if result["decision"] == "COUNTEROFFER":
            self.assertLess(result["approved_amount"], application["requested_amount"])
            self.assertGreaterEqual(result["approved_amount"], 1229.13)

    def test_bureau_is_not_blended_into_aidflow_profile_score(self):
        sources = [
            get_alternative_data(s, BASE_APPLICATION["applicant_id"], BASE_APPLICATION)
            for s in SOURCE_IDS
        ]
        aidflow = score_customer_profile(sources)
        same_aidflow = score_customer_profile(sources)
        self.assertEqual(
            aidflow["complex_customer_profile_score"],
            same_aidflow["complex_customer_profile_score"],
        )
        self.assertNotIn("bureau_score", aidflow)


if __name__ == "__main__":
    unittest.main()
