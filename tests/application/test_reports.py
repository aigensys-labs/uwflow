"""Tests for Core Stage 7 applicant report generation and output contracts."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

from tools.demo.run import DEFAULT_APPLICATION, run
from report_renderer import generate_reports, render_html


class UnderwritingReportTests(unittest.TestCase):
    def test_default_decision_generates_html_pdf_and_json(self):
        decision = run(DEFAULT_APPLICATION.copy())
        with tempfile.TemporaryDirectory() as tmp:
            files = generate_reports(decision, tmp)
            self.assertTrue(files["html"].is_file())
            self.assertTrue(files["pdf"].is_file())
            self.assertTrue(files["json"].is_file())
            self.assertTrue(files["pdf"].read_bytes().startswith(b"%PDF-"))
            html = files["html"].read_text(encoding="utf-8")
            self.assertIn("John Jones", html)
            self.assertIn("UWflow", html)
            self.assertIn("APPROVED", html)
            self.assertIn("€8,194.20", html)
            self.assertIn("AIDflow profile inputs", html)
            self.assertEqual(html.count('class="score-line"'), 10)
            parsed = json.loads(files["json"].read_text(encoding="utf-8"))
            self.assertEqual(parsed["decision"], decision["decision"])
            self.assertEqual(parsed["engine"], "UWflow Underwriting Engine")
            self.assertEqual(parsed["aidflow_scoring"]["input_score_count"], 10)
            self.assertEqual(parsed["complex_customer_profile_score"], 837)

    def test_report_shows_task_runtime_provenance_when_supplied(self):
        decision = run(DEFAULT_APPLICATION.copy())
        decision["runtime_provenance"] = {
            "integrity_status": "VERIFIED",
            "runtime_release": "2.0.0",
            "source_ref": "v2.0.0",
            "runtime_file_count": 9,
            "release_manifest_sha256": "a" * 64,
            "task_runner": "io.kestra.plugin.scripts.runner.docker.Docker",
            "python_version": "3.11.18",
            "python_task_image": "ai/uwflow-core-runtime:2.0.0",
        }
        html = render_html(decision)
        self.assertIn("Task runner", html)
        self.assertIn("3.11.18", html)
        self.assertIn("ai/uwflow-core-runtime:2.0.0", html)
        with tempfile.TemporaryDirectory() as tmp:
            files = generate_reports(decision, tmp)
            self.assertTrue(files["pdf"].read_bytes().startswith(b"%PDF-"))

    def test_report_renderer_handles_early_decline_without_score_or_affordability(self):
        application = DEFAULT_APPLICATION.copy()
        application["monthly_income"] = 500.0
        result = run(application)
        self.assertEqual(result["decision"], "DECLINED")
        html = render_html(result)
        self.assertIn("Not scored", html)
        self.assertIn("Affordability was not calculated", html)
        with tempfile.TemporaryDirectory() as tmp:
            files = generate_reports(result, tmp)
            self.assertTrue(files["pdf"].stat().st_size > 1000)

    def test_report_renderer_handles_manual_review(self):
        application = {**DEFAULT_APPLICATION, "data_sharing_consent": False}
        result = run(application)
        self.assertEqual(result["decision"], "REFER")
        html = render_html(result)
        self.assertIn("REFER FOR REVIEW", html)
        self.assertIn("No alternative-data sources were queried", html)

    def test_counteroffer_report_is_rendered(self):
        scenario = json.loads(
            (
                ROOT
                / "core"
                / "underwriting"
                / "examples"
                / "applications"
                / "application_counteroffer.json"
            ).read_text(encoding="utf-8")
        )
        result = run(scenario)
        self.assertEqual(result["decision"], "COUNTEROFFER")
        with tempfile.TemporaryDirectory() as tmp:
            files = generate_reports(result, tmp)
            self.assertIn("COUNTEROFFER", files["html"].read_text(encoding="utf-8"))
            self.assertTrue(files["pdf"].read_bytes().startswith(b"%PDF-"))

    def test_bureau_decline_report_is_rendered(self):
        scenario = json.loads(
            (
                ROOT
                / "core"
                / "underwriting"
                / "examples"
                / "applications"
                / "application_bureau_decline.json"
            ).read_text(encoding="utf-8")
        )
        result = run(scenario)
        self.assertEqual(result["decision"], "DECLINED")
        html = render_html(result)
        self.assertIn("Bureau assessment", html)
        self.assertIn("DECLINED", html)

    def test_report_escapes_untrusted_applicant_name(self):
        application = {**DEFAULT_APPLICATION, "applicant_name": '<script>alert("x")</script>'}
        result = run(application)
        html = render_html(result)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("x")</script>', html)


if __name__ == "__main__":
    unittest.main()
