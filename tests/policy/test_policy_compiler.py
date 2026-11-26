"""Tests for typed policy validation and deterministic Python compilation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

import policy_generated
from alternative_data import SOURCE_IDS
from hard_gates import evaluate_hard_gates
from tools.policy.compiler import (
    DEFAULT_FIELD_CATALOG,
    DEFAULT_SPEC_DIR,
    DEFAULT_OUTPUT,
    PolicyValidationError,
    compile_specs,
    validate_dmn_table,
    validate_routing_dag,
)


class PolicyCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.field_catalog = json.loads(DEFAULT_FIELD_CATALOG.read_text(encoding="utf-8"))
        self.dmn = json.loads(
            (DEFAULT_SPEC_DIR / "stage1_hard_gates.json").read_text(encoding="utf-8")
        )
        self.routing = json.loads(
            (DEFAULT_SPEC_DIR / "stage3_source_plan.json").read_text(encoding="utf-8")
        )

    def test_checked_in_generated_module_is_deterministic_and_current(self) -> None:
        generated, _ = compile_specs()
        self.assertEqual(DEFAULT_OUTPUT.read_text(encoding="utf-8"), generated)

    def test_stage1_generated_checks_match_policy_reference_cases(self) -> None:
        snapshots = json.loads(
            (ROOT / "tests" / "fixtures" / "stage1_policy_reference_cases.json").read_text(
                encoding="utf-8"
            )
        )
        for snapshot in snapshots:
            with self.subTest(scenario=snapshot["scenario"]):
                generated = policy_generated.evaluate_stage1_hard_gates(snapshot["context"])
                self.assertEqual(generated["checks"], snapshot["expected_checks"])
                wrapper = evaluate_hard_gates(snapshot["application"])
                self.assertEqual(wrapper["checks"], snapshot["expected_checks"])
                self.assertEqual(wrapper["policy_trace"], generated["trace"])
                self.assertEqual(len(generated["checks"]), 6)
                self.assertEqual(len(generated["trace"]), 6)

    def test_stage1_collect_policy_preserves_multiple_simultaneous_failures(self) -> None:
        result = policy_generated.evaluate_stage1_hard_gates(
            {
                "validation_error_count": 0,
                "applicant_age": 17,
                "monthly_income": 500.0,
                "employment_status": "UNEMPLOYED",
                "requested_amount": 500.0,
                "loan_term_months": 18,
            }
        )
        failed = [item["check_id"] for item in result["checks"] if item["status"] == "FAIL"]
        self.assertEqual(
            failed,
            ["MINIMUM_AGE", "MINIMUM_INCOME", "EMPLOYMENT_STATUS", "REQUEST_AMOUNT", "LOAN_TERM"],
        )
        self.assertEqual(len(result["checks"]), 6)

    def test_stage1_policy_threshold_boundaries_are_inclusive(self) -> None:
        for age, income, amount, term in (
            (18, 655.54, 1229.13, 12),
            (75, 655.54, 40971.00, 84),
        ):
            with self.subTest(age=age, income=income, amount=amount, term=term):
                result = policy_generated.evaluate_stage1_hard_gates(
                    {
                        "validation_error_count": 0,
                        "applicant_age": age,
                        "monthly_income": income,
                        "employment_status": "FULL_TIME",
                        "requested_amount": amount,
                        "loan_term_months": term,
                    }
                )
                self.assertTrue(all(check["status"] == "PASS" for check in result["checks"]))

    def test_stage1_uses_one_positive_predicate_per_input_field(self) -> None:
        check_fields = [check["field"] for check in self.dmn["checks"]]
        input_fields = [item["field"] for item in self.dmn["inputs"]]
        self.assertEqual(len(check_fields), len(set(check_fields)))
        self.assertEqual(set(check_fields), set(input_fields))
        self.assertTrue(
            all(
                set(check)
                == {"check_id", "field", "description", "valid_when", "failure_reason_code"}
                for check in self.dmn["checks"]
            )
        )
        self.assertNotIn("rules", self.dmn)
        self.assertNotIn("default_result", self.dmn)

        context = {
            "validation_error_count": 0,
            "applicant_age": 17,
            "monthly_income": 1966.61,
            "employment_status": "FULL_TIME",
            "requested_amount": 8194.20,
            "loan_term_months": 60,
        }
        result = policy_generated.evaluate_stage1_hard_gates(context)
        age_check = next(item for item in result["checks"] if item["check_id"] == "MINIMUM_AGE")
        self.assertEqual(age_check["status"], "FAIL")
        self.assertEqual(age_check["reason_code"], "AGE_OUT_OF_POLICY")
        self.assertEqual(result["trace"], [check["check_id"] for check in self.dmn["checks"]])

    def test_stage1_requires_all_typed_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing policy input"):
            policy_generated.evaluate_stage1_hard_gates({})
        invalid = {
            "validation_error_count": False,
            "applicant_age": 30,
            "monthly_income": 2000.0,
            "employment_status": "FULL_TIME",
            "requested_amount": 5000.0,
            "loan_term_months": 36,
        }
        with self.assertRaisesRegex(ValueError, "validation_error_count.*integer"):
            policy_generated.evaluate_stage1_hard_gates(invalid)

    def test_stage3_source_plan_matches_existing_consent_and_decline_gate(self) -> None:
        scenarios = [
            (True, "PASS", True, True),
            (False, "PASS", True, False),
            (True, "DECLINE", True, False),
            (True, "PASS", False, False),
            (True, "REFER", True, True),
            (True, "REVIEW", True, True),
        ]
        for gates_passed, bureau_status, consent, should_collect in scenarios:
            with self.subTest(
                gates_passed=gates_passed,
                bureau_status=bureau_status,
                consent=consent,
            ):
                result = policy_generated.build_stage3_source_plan(
                    {
                        "hard_gates_passed": gates_passed,
                        "bureau_decision_status": bureau_status,
                        "data_sharing_consent": consent,
                    }
                )
                self.assertEqual(result["planned_count"], len(SOURCE_IDS) if should_collect else 0)
                self.assertEqual(result["source_ids"], SOURCE_IDS if should_collect else [])
                self.assertEqual(
                    result["action"],
                    "COLLECT_SOURCES" if should_collect else "SKIP_SOURCE_COLLECTION",
                )
                self.assertEqual(
                    result["loop_values"],
                    SOURCE_IDS if should_collect else ["__NO_SOURCE_COLLECTION__"],
                )

    def test_stage3_trace_contains_only_the_executed_path(self) -> None:
        collected = policy_generated.build_stage3_source_plan(
            {
                "hard_gates_passed": True,
                "bureau_decision_status": "PASS",
                "data_sharing_consent": True,
            }
        )
        skipped = policy_generated.build_stage3_source_plan(
            {
                "hard_gates_passed": False,
                "bureau_decision_status": "PASS",
                "data_sharing_consent": True,
            }
        )
        self.assertEqual(
            collected["trace"],
            ["n_hard_gates", "n_bureau", "n_consent", "out_collect_sources"],
        )
        self.assertEqual(skipped["trace"], ["n_hard_gates", "out_skip_sources"])

    def test_stage3_never_executes_source_io(self) -> None:
        result = policy_generated.build_stage3_source_plan(
            {
                "hard_gates_passed": True,
                "bureau_decision_status": "PASS",
                "data_sharing_consent": True,
            }
        )
        self.assertEqual(
            set(result), {"action", "source_ids", "loop_values", "planned_count", "reason", "trace"}
        )
        self.assertNotIn("provider", result)
        self.assertNotIn("result_json", result)

    def test_stage3_requires_all_typed_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing policy input"):
            policy_generated.build_stage3_source_plan({})
        with self.assertRaisesRegex(ValueError, "data_sharing_consent.*boolean"):
            policy_generated.build_stage3_source_plan(
                {
                    "hard_gates_passed": True,
                    "bureau_decision_status": "PASS",
                    "data_sharing_consent": "yes",
                }
            )

    def test_dmn_rejects_unlisted_fields_and_operators(self) -> None:
        invalid_field = deepcopy(self.dmn)
        invalid_field["checks"][0]["field"] = "raw_bureau_payload"
        with self.assertRaisesRegex(PolicyValidationError, "not in the allow-list"):
            validate_dmn_table(invalid_field, self.field_catalog)

        invalid_operator = deepcopy(self.dmn)
        invalid_operator["checks"][0]["valid_when"]["op"] = "python"
        with self.assertRaisesRegex(PolicyValidationError, "Unsupported operator"):
            validate_dmn_table(invalid_operator, self.field_catalog)

    def test_dmn_rejects_duplicate_policy_field_checks(self) -> None:
        invalid = deepcopy(self.dmn)
        invalid["checks"][1]["field"] = invalid["checks"][0]["field"]
        with self.assertRaisesRegex(PolicyValidationError, "more than one policy check"):
            validate_dmn_table(invalid, self.field_catalog)

    def test_dmn_requires_exactly_one_check_for_every_declared_input(self) -> None:
        invalid = deepcopy(self.dmn)
        invalid["checks"].pop()
        with self.assertRaisesRegex(PolicyValidationError, "exactly one positive predicate"):
            validate_dmn_table(invalid, self.field_catalog)

    def test_routing_dag_rejects_cycles(self) -> None:
        invalid = deepcopy(self.routing)
        invalid["edges"].append(
            {
                "id": "e_cycle_back",
                "source": "n_consent",
                "target": "n_hard_gates",
                "condition": {"field": "data_sharing_consent", "op": "==", "value": False},
                "priority": 20,
                "is_default": False,
            }
        )
        with self.assertRaisesRegex(PolicyValidationError, "cycle"):
            validate_routing_dag(invalid, self.field_catalog)

    def test_routing_dag_requires_one_default_per_split(self) -> None:
        invalid = deepcopy(self.routing)
        invalid["edges"] = [
            edge for edge in invalid["edges"] if edge["id"] != "e_hard_gates_default"
        ]
        with self.assertRaisesRegex(PolicyValidationError, "exactly one default"):
            validate_routing_dag(invalid, self.field_catalog)

    def test_routing_dag_rejects_unreachable_nodes(self) -> None:
        invalid = deepcopy(self.routing)
        invalid["nodes"].append(
            {
                "id": "out_unreachable",
                "type": "outcome",
                "label": "Unreachable outcome",
                "action": "SKIP_SOURCE_COLLECTION",
                "reason": "UNREACHABLE",
            }
        )
        with self.assertRaisesRegex(PolicyValidationError, "unreachable"):
            validate_routing_dag(invalid, self.field_catalog)

    def test_routing_dag_rejects_source_ids_outside_catalogue(self) -> None:
        invalid = deepcopy(self.routing)
        invalid["nodes"][3]["source_ids"][0] = "not_a_real_source"
        with self.assertRaisesRegex(PolicyValidationError, "invalid or duplicate source IDs"):
            validate_routing_dag(invalid, self.field_catalog)

    def test_policy_source_catalogue_matches_runtime_adapter_catalogue(self) -> None:
        self.assertEqual(self.field_catalog["source_ids"], SOURCE_IDS)
        plan_node = next(node for node in self.routing["nodes"] if node["type"] == "source_plan")
        self.assertEqual(plan_node["source_ids"], SOURCE_IDS)

    def test_compiled_policy_module_contains_no_dynamic_code_execution(self) -> None:
        generated_source = DEFAULT_OUTPUT.read_text(encoding="utf-8")
        self.assertNotIn("eval(", generated_source)
        self.assertNotIn("exec(", generated_source)
        self.assertNotIn("compile(", generated_source)

    def test_policy_field_catalogue_does_not_expose_aidflow_inputs(self) -> None:
        fields = set(self.field_catalog["fields"])
        self.assertTrue(
            fields.isdisjoint(
                {
                    "profile_input_score",
                    "raw_bureau_payload",
                    "monthly_debt_payments",
                    "applicant_income_document",
                }
            )
        )

    def test_current_runtime_snapshot_matches_canonical_core_source(self) -> None:
        snapshot = ROOT / "core" / "kestra" / "namespace-files" / "runtime" / "releases" / "2.0.0"
        source = ROOT / "core" / "python" / "runtime"
        manifest = json.loads((snapshot / "release-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_version"], "2.0.0")
        self.assertEqual(set(manifest["files"]), {path.name for path in source.glob("*.py")})
        for filename, expected_hash in manifest["files"].items():
            with self.subTest(module=filename):
                snapshot_bytes = (snapshot / filename).read_bytes()
                self.assertEqual(snapshot_bytes, (source / filename).read_bytes())
                self.assertEqual(hashlib.sha256(snapshot_bytes).hexdigest(), expected_hash)

    def test_stage3_kestra_task_uses_compiled_plan_but_keeps_existing_loop(self) -> None:
        import yaml

        flow = yaml.safe_load(
            (ROOT / "core" / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
                encoding="utf-8"
            )
        )
        stage3 = next(task for task in flow["tasks"] if task["id"] == "stage3_source_plan")
        stage3_script = stage3["script"]
        self.assertIn("from policy_generated import build_stage3_source_plan", stage3_script)
        self.assertNotIn("from alternative_data import SOURCE_IDS", stage3_script)
        stage4 = next(task for task in flow["tasks"] if task["id"] == "stage4_bigdata_fanout")
        self.assertEqual(stage4["type"], "io.kestra.plugin.core.flow.Loop")
        self.assertEqual(stage4["concurrencyLimit"], 10)
        self.assertEqual(stage4["values"], "{{ outputs.stage3_source_plan.vars.loop_values }}")
