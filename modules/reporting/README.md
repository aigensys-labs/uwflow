# Reporting

Reporting turns paired replay outputs into comparative decision, score, segment, source-coverage and migration analysis, with HTML and PDF deliverables. It presents evaluation results; it does not recalculate underwriting decisions or establish profitability, PD or loss performance from synthetic data. Core's individual applicant decision report remains part of Core.

## Use Reporting

| Guide | Use it to… |
|---|---|
| [Champion vs Challenger report](../../docs/development/champion-challenger-impact-report.md) | Interpret the CRO report, approval/offer movement, stage outcomes, score deciles, segments, source coverage and case-level migrations. |
| [End-to-end DEV workflow](../../docs/development/end-to-end-dev-workflow.md) | Generate the comparison reports from a paired baseline/candidate replay. |

The report generator is implemented in `modules/reporting/tools/impact_report.py`. Synthetic replay outputs are engineering and policy-comparison evidence, not observed repayment performance.
