"""Generate self-contained HTML and PDF underwriting decision reports.

The renderer is intentionally presentation-only: it consumes the decision JSON
and never recalculates a score, policy outcome, affordability amount or price.
All figures are synthetic demonstration output and must not be used for lending.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import json
from pathlib import Path
from typing import Any


DECISION_META = {
    "APPROVED": ("APPROVED", "Decision approved under the illustrative demo policy.", "success"),
    "COUNTEROFFER": ("COUNTEROFFER", "The requested amount was reduced to the illustrative affordability limit.", "info"),
    "REFER": ("REFER FOR REVIEW", "Automated decisioning is paused. A qualified underwriter must review the application.", "warning"),
    "DECLINED": ("DECLINED", "The application did not meet one or more illustrative demo policy requirements.", "danger"),
}

REASON_LABELS = {
    "PROFILE_AND_AFFORDABILITY_WITHIN_UWFLOW_POLICY": "Customer profile and affordability checks passed",
    "REQUEST_REDUCED_TO_AFFORDABLE_AMOUNT": "Requested amount reduced to the affordable amount",
    "INCOME_BELOW_POLICY_FLOOR": "Gross monthly income is below the demo policy floor",
    "AGE_OUT_OF_POLICY": "Applicant age is outside the demo eligibility range",
    "UNEMPLOYED_STATUS": "Employment status does not meet the demo product criteria",
    "REQUEST_AMOUNT_OUT_OF_RANGE": "Requested amount is outside the demo product range",
    "UNSUPPORTED_LOAN_TERM": "Requested loan term is not supported",
    "INVALID_APPLICATION_DATA": "Application data is incomplete or invalid",
    "BUREAU_PUBLIC_RECORD": "Synthetic bureau response indicates a public-record flag",
    "MULTIPLE_ACTIVE_DELINQUENCIES": "Synthetic bureau response indicates multiple active delinquencies",
    "BUREAU_SCORE_BELOW_MINIMUM": "Synthetic bureau score is below the demo minimum",
    "BUREAU_SCORE_REVIEW_BAND": "Synthetic bureau score is within the manual-review band",
    "ACTIVE_DELINQUENCY_REVIEW": "An active delinquency requires manual review",
    "MANUAL_UNDERWRITER_REVIEW_REQUIRED": "Manual underwriter review is required",
    "INSUFFICIENT_CREDIT_SIGNAL_COVERAGE": "Insufficient repayment-data coverage for automated scoring",
    "BUREAU_DATA_UNAVAILABLE": "Bureau information was unavailable",
    "PROFILE_SCORE_BELOW_MINIMUM_POLICY_THRESHOLD": "AIDflow profile score is below the UWflow policy threshold",
    "PROFILE_SCORE_IN_MANUAL_REVIEW_BAND": "AIDflow profile score is within the manual-review band",
    "AIDFLOW_PROFILE_SCORE_UNAVAILABLE": "AIDflow could not return a complete profile score",
    "AIDFLOW_INPUT_COVERAGE_INCOMPLETE": "AIDflow did not receive all ten required source scores",
    "INSUFFICIENT_AFFORDABILITY_CAPACITY": "Income and existing obligations do not support the minimum offer",
    "SOURCE_COLLECTION_NOT_PERMITTED_OR_NOT_REQUIRED": "Alternative-data collection was not permitted or required",
}

ROLE_LABELS = {
    "CREDIT_SIGNAL": "Repayment signal",
    "FRAUD_CONTROL": "Fraud control",
    "IDENTITY_CONTROL": "Identity control",
    "INFORMATIONAL_ONLY": "Informational only",
}


def _s(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _safe(value: Any, default: str = "—") -> str:
    return escape(_s(value, default), quote=True)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _money(value: Any, currency: str = "EUR", *, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = Decimal(str(value)).quantize(Decimal("1") / (Decimal(10) ** decimals), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return "—"
    symbol = {"EUR": "€", "USD": "$", "GBP": "£", "CZK": "Kč"}.get(currency, currency + " ")
    if symbol == "Kč":
        return f"{number:,.{decimals}f} {symbol}"
    return f"{symbol}{number:,.{decimals}f}"


def _pct(value: Any, *, already_percent: bool = False, decimals: int = 1) -> str:
    if value is None:
        return "—"
    number = _num(value)
    if not already_percent:
        number *= 100
    return f"{number:.{decimals}f}%"


def _pretty(value: Any) -> str:
    text = _s(value, "")
    if not text:
        return "—"
    rendered = text.replace("_", " ").strip().title()
    # Preserve product-name casing when rendering identifiers and audit events.
    return rendered.replace("Aidflow", "AIDflow").replace("Uwflow", "UWflow")


def _reason(code: Any) -> str:
    code_text = _s(code, "")
    return REASON_LABELS.get(code_text, _pretty(code_text))


def _date(value: Any) -> str:
    text = _s(value, "")
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y · %H:%M UTC")
    except ValueError:
        return text


def _status_class(value: Any) -> str:
    key = _s(value, "").upper()
    if key in {"APPROVED", "PASS", "SUCCESS", "CLEAR", "FINAL"}:
        return "success"
    if key in {"COUNTEROFFER"}:
        return "info"
    if key in {"REFER", "REVIEW", "PENDING_MANUAL_REVIEW"}:
        return "warning"
    if key in {"DECLINED", "DECLINE", "FAIL", "ALERT"}:
        return "danger"
    return "neutral"


def _decision_text(result: dict[str, Any]) -> tuple[str, str, str]:
    decision = _s(result.get("decision"), "REFER").upper()
    return DECISION_META.get(decision, (decision, "Decision status requires review.", "neutral"))


def _source_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("source_results") or []
    return sorted(rows, key=lambda x: (x.get("source_role", ""), x.get("source_id", "")))


def _policy_detail(check: dict[str, Any], currency: str) -> str:
    reason_codes = check.get("reason_codes") or []
    if reason_codes:
        return ", ".join(_reason(x) for x in reason_codes)
    check_id = _s(check.get("check_id"), "")
    if "observed_weight" in check:
        return f"Coverage {_pct(check.get('observed_weight'))}; minimum {_pct(check.get('minimum_weight'))}"
    if check_id in {"MAX_DTI", "MAX_PAYMENT_TO_INCOME"} and "limit" in check:
        return f"Maximum {_pct(check.get('limit'))}"
    if check_id == "MINIMUM_OFFER_AMOUNT" and "minimum" in check:
        return f"Minimum {_money(check.get('minimum'), currency)}"
    if check_id in {"MINIMUM_COMPOSITE_SCORE", "MINIMUM_PROFILE_SCORE", "MINIMUM_AUTOMATED_PROFILE_SCORE"} and "minimum" in check:
        return f"Score {_s(check.get('score'))}; minimum {_s(check.get('minimum'))}"
    if "description" in check:
        return _s(check.get("description"))
    if "minimum" in check:
        return f"Minimum {_s(check.get('minimum'))}"
    if "limit" in check:
        return f"Limit {_s(check.get('limit'))}"
    return "—"


def _html_policy_rows(checks: list[dict[str, Any]], currency: str) -> str:
    if not checks:
        return '<tr><td colspan="3" class="empty">No policy checks were run.</td></tr>'
    output = []
    for check in checks:
        status = _s(check.get("status"), "UNKNOWN").upper()
        detail = _policy_detail(check, currency)
        output.append(
            f'<tr><td>{_safe(_pretty(check.get("check_id")))}</td>'
            f'<td><span class="pill {_status_class(status)}">{_safe(status)}</span></td>'
            f'<td>{_safe(detail)}</td></tr>'
        )
    return "".join(output)


def render_html(result: dict[str, Any]) -> str:
    """Render a responsive, self-contained HTML underwriting report."""
    currency = _s(result.get("currency"), "EUR")
    decision = _s(result.get("decision"), "REFER").upper()
    decision_label, narrative, decision_class = _decision_text(result)
    affordability = result.get("affordability") or {}
    bureau = result.get("bureau_assessment") or {}
    aidflow_scoring = result.get("aidflow_scoring") or {}
    source_rows = _source_rows(result)
    policy_checks = result.get("policy_checks") or []
    audit_events = result.get("audit_events") or []
    runtime_provenance = result.get("runtime_provenance") or {}
    decision_factors = result.get("principal_decision_factors") or []
    reason_codes = result.get("reason_codes") or []

    score = result.get("complex_customer_profile_score")
    amount = result.get("approved_amount", 0) or 0
    apr = result.get("offered_apr_percent", result.get("indicative_apr_percent"))
    term = result.get("loan_term_months")

    profile_inputs = aidflow_scoring.get("input_scores") or []
    coverage = aidflow_scoring.get("input_coverage", 0.0)
    input_count = aidflow_scoring.get("input_score_count", 0)
    expected_count = aidflow_scoring.get("expected_input_count", 10)

    metric_cards = [
        ("COMPLEX CUSTOMER PROFILE SCORE", str(int(score)) + " / 900" if score is not None else "Not scored", "AIDflow inference result"),
        ("RISK TIER", _pretty(result.get("risk_tier")), "Illustrative pricing band"),
        ("APPROVED AMOUNT", _money(amount, currency), "Principal offered"),
        ("OFFERED APR", _pct(apr, already_percent=True, decimals=2), f"{term or '—'} month term"),
    ]
    metric_html = "".join(
        f'<div class="metric"><div class="metric-label">{_safe(label)}</div><div class="metric-value">{_safe(value)}</div><div class="metric-note">{_safe(note)}</div></div>'
        for label, value, note in metric_cards
    )

    if affordability:
        affordability_items = [
            ("Gross monthly income", _money(affordability.get("monthly_income_used"), currency)),
            ("Existing monthly debt", _money(affordability.get("existing_monthly_debt_payments_used"), currency)),
            ("Monthly housing cost", _money(affordability.get("monthly_housing_cost"), currency)),
            ("Proposed instalment", _money(affordability.get("proposed_monthly_installment"), currency)),
            ("Post-offer DTI", _pct(affordability.get("post_offer_dti"))),
            ("Payment-to-income", _pct(affordability.get("post_offer_pti"))),
            ("Residual monthly income", _money(affordability.get("residual_income_after_debt_housing_and_offer"), currency)),
            ("Maximum affordable principal", _money(affordability.get("maximum_affordable_principal"), currency)),
            ("Total repayment", _money(result.get("total_repayment"), currency)),
            ("Total interest", _money(result.get("total_interest"), currency)),
        ]
        affordability_html = "".join(
            f'<div class="detail-row"><span>{_safe(label)}</span><strong>{_safe(value)}</strong></div>'
            for label, value in affordability_items
        )
    else:
        affordability_html = '<div class="empty-panel">Affordability was not calculated because the application did not reach offer assessment.</div>'

    if bureau:
        bureau_items = [
            ("Bureau status", _pretty(bureau.get("decision_status", bureau.get("status")))),
            ("Bureau score", _s(bureau.get("bureau_score"))),
            ("Active delinquencies", _s(bureau.get("active_delinquencies"))),
            ("Revolving utilisation", _pct(bureau.get("revolving_utilization"))),
            ("Recent enquiries · 6 months", _s(bureau.get("recent_inquiries_6m"))),
            ("Open accounts", _s(bureau.get("total_open_accounts"))),
        ]
        bureau_html = "".join(
            f'<div class="detail-row"><span>{_safe(label)}</span><strong>{_safe(value)}</strong></div>'
            for label, value in bureau_items
        )
    else:
        bureau_html = '<div class="empty-panel">Bureau assessment was not run.</div>'

    score_items = []
    if score is not None and profile_inputs:
        for item in profile_inputs:
            score_value = _num(item.get("input_score_0_100"))
            weight = _num(item.get("weight"))
            score_items.append((
                _s(item.get("source_name", item.get("source_id"))),
                score_value,
                score_value,
                f"{score_value:.1f} / 100 · {_pct(weight, decimals=0)} weight · contribution {_num(item.get('weighted_contribution')):.2f}",
            ))
    score_html = "".join(
        f'<div class="score-line"><div class="score-line-head"><span>{_safe(label)}</span><strong>{score_value:.1f}<small> / 100</small></strong></div>'
        f'<div class="track"><div class="fill" style="width:{max(0, min(100, bar_pct)):.1f}%"></div></div><div class="score-equation">{_safe(equation)}</div></div>'
        for label, score_value, bar_pct, equation in score_items
    ) or '<div class="empty-panel">AIDflow did not produce a customer profile score.</div>'
    score_html += f'<div class="coverage-note">AIDflow input coverage: <strong>{_safe(input_count)} / {_safe(expected_count)} ({_pct(coverage)})</strong></div>'

    source_table_rows = []
    for source in source_rows:
        status = _s(source.get("status"), "UNKNOWN").upper()
        role = ROLE_LABELS.get(_s(source.get("source_role")), _pretty(source.get("source_role")))
        signal = source.get("profile_input_score")
        result_value = f"Profile input {signal:.1f}/100" if isinstance(signal, (float, int)) else _pretty(source.get("risk_level", source.get("coverage", status)))
        source_table_rows.append(
            f'<tr><td><strong>{_safe(source.get("source_name", source.get("source_id")))}</strong><span class="subcell">{_safe(source.get("provider"))}</span></td>'
            f'<td>{_safe(role)}</td><td><span class="pill {_status_class(status)}">{_safe(status)}</span></td>'
            f'<td>{_safe(result_value)}</td><td>{_safe(_s(source.get("latency_ms"), "—"))} ms</td></tr>'
        )
    source_table = "".join(source_table_rows) or '<tr><td colspan="5" class="empty">No alternative-data sources were queried.</td></tr>'

    policy_table = _html_policy_rows(policy_checks, currency)
    factor_html = "".join(f'<li>{_safe(_reason(item))}</li>' for item in decision_factors) or "<li>No additional decision factors recorded.</li>"
    reason_html = "".join(f'<span class="reason-tag">{_safe(_reason(code))}</span>' for code in reason_codes) or '<span class="muted">No reason codes supplied.</span>'
    audit_rows = "".join(
        f'<tr><td>{_safe(_date(item.get("timestamp")))}</td><td>{_safe(_pretty(item.get("event")))}</td><td><span class="pill {_status_class(item.get("status"))}">{_safe(_pretty(item.get("status")))}</span></td></tr>'
        for item in audit_events
    ) or '<tr><td colspan="3" class="empty">No audit events captured.</td></tr>'

    manifest_hash = _s(runtime_provenance.get("release_manifest_sha256"), "Not attached")
    if manifest_hash != "Not attached":
        manifest_hash = manifest_hash[:20] + "…"
    task_image = _s(runtime_provenance.get("python_task_image"), "Not attached")
    if "@sha256:" in task_image:
        image_name, image_digest = task_image.split("@sha256:", 1)
        task_image = f"{image_name}@sha256:{image_digest[:20]}…"
    runtime_rows = [
        ("Runtime release", _s(runtime_provenance.get("runtime_release"), "Local / unversioned")),
        ("Source ref", _s(runtime_provenance.get("source_ref"), "Not attached")),
        ("Integrity", _s(runtime_provenance.get("integrity_status"), "NOT VERIFIED")),
        ("Runtime files", _s(runtime_provenance.get("runtime_file_count"), "—")),
        ("Task runner", _s(runtime_provenance.get("task_runner"), "Not attached")),
        ("Python runtime", _s(runtime_provenance.get("python_version"), "Not attached")),
        ("Task image", task_image),
        ("Manifest SHA-256", manifest_hash),
    ]
    runtime_provenance_html = "".join(
        f'<div class="detail-row"><span>{_safe(label)}</span><strong>{_safe(value)}</strong></div>'
        for label, value in runtime_rows
    )

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>UWflow Underwriting Decision · {_safe(result.get('decision_reference'))}</title>
<style>
:root{{--ink:#142033;--muted:#66758a;--line:#e4eaf2;--paper:#f4f7fb;--white:#fff;--navy:#101d32;--blue:#3d6fe0;--teal:#22a69a;--success:#16804a;--warning:#a86408;--danger:#b42332;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
.page{{max-width:1160px;margin:34px auto;padding:0 22px 36px}}.report{{background:var(--white);border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 18px 55px rgba(16,29,50,.08)}}
.topbar{{background:linear-gradient(115deg,#101d32,#1c3354);color:#fff;padding:26px 30px;display:flex;align-items:center;justify-content:space-between;gap:20px}}
.brand{{display:flex;align-items:center;gap:13px}}.mark{{width:44px;height:44px;border:1px solid rgba(255,255,255,.25);border-radius:13px;display:grid;place-items:center;font-weight:800;letter-spacing:-1px;background:rgba(255,255,255,.08)}}
.brand-name{{font-size:22px;font-weight:750;letter-spacing:.2px}}.brand-sub{{font-size:10px;letter-spacing:1.65px;text-transform:uppercase;color:#b9c9dd;margin-top:2px}}
.top-meta{{text-align:right;color:#b9c9dd;font-size:11px;line-height:1.8}}.top-meta strong{{display:block;color:#fff;font-size:13px;font-weight:650}}
.body{{padding:28px 30px 30px}}.applicant-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:22px}}.eyebrow,.metric-label,.section-kicker{{color:var(--muted);font-size:10px;font-weight:750;letter-spacing:1.15px;text-transform:uppercase}}
.applicant-name{{font-size:25px;font-weight:760;letter-spacing:-.5px;margin:3px 0 2px}}.applicant-id{{font-size:12px;color:var(--muted)}}.decision-panel{{display:flex;align-items:center;gap:12px;max-width:440px}}
.decision-copy{{display:flex;flex-direction:column;gap:2px;text-align:right;color:var(--muted);font-size:12px}}.decision-copy strong{{font-size:14px;color:var(--ink)}}.pill{{display:inline-flex;align-items:center;justify-content:center;padding:5px 10px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.55px;white-space:nowrap}}
.pill.success{{background:#e6f5ed;color:var(--success)}}.pill.info{{background:#e9f0ff;color:#2458bf}}.pill.warning{{background:#fff3dc;color:var(--warning)}}.pill.danger{{background:#fdebed;color:var(--danger)}}.pill.neutral{{background:#edf1f6;color:#5f6b7d}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0 25px}}.metric{{background:#f7f9fc;border:1px solid var(--line);border-radius:13px;padding:15px 16px;min-height:100px}}.metric-value{{font-size:23px;line-height:1.25;font-weight:770;letter-spacing:-.55px;margin-top:8px;overflow-wrap:anywhere}}.metric-note{{color:var(--muted);font-size:11px;margin-top:4px}}
.decision-banner{{border-radius:12px;padding:14px 16px;margin:0 0 25px;display:flex;gap:12px;align-items:flex-start;border:1px solid var(--line);background:#f8fafc}}.decision-banner.success{{background:#f0faf4;border-color:#d3eddd}}.decision-banner.warning{{background:#fff9ed;border-color:#f5e5c2}}.decision-banner.danger{{background:#fff4f4;border-color:#f4d8dc}}.decision-banner.info{{background:#f1f6ff;border-color:#dbe6ff}}.decision-banner strong{{display:block;font-size:12px;margin-bottom:2px}}.decision-banner p{{margin:0;color:#526176;font-size:12px}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:0 0 18px}}.panel{{border:1px solid var(--line);border-radius:14px;padding:17px 18px;min-width:0}}.section-title{{font-size:14px;font-weight:760;margin:0 0 14px;display:flex;justify-content:space-between;align-items:center;gap:10px}}.section-title small{{font-size:10px;color:var(--muted);font-weight:550}}
.detail-row{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:7px 0;border-bottom:1px solid #eff2f6;font-size:12px}}.detail-row:last-child{{border-bottom:0}}.detail-row span{{color:var(--muted)}}.detail-row strong{{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}}
.score-line{{margin:0 0 16px}}.score-line-head{{display:flex;justify-content:space-between;gap:10px;font-size:12px}}.score-line-head strong{{font-variant-numeric:tabular-nums}}.score-line-head small{{color:var(--muted);font-weight:500}}.track{{height:8px;border-radius:20px;background:#edf1f6;overflow:hidden;margin:7px 0 5px}}.fill{{height:100%;border-radius:20px;background:linear-gradient(90deg,var(--blue),var(--teal))}}.score-equation,.coverage-note{{font-size:10px;color:var(--muted)}}.penalties{{padding:9px 11px;border-radius:9px;background:#fff7e8;color:#86540f;font-size:11px}}.penalties ul{{margin:5px 0 0;padding-left:17px}}.coverage-note{{margin-top:11px}}
.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:11px}}th{{text-align:left;color:#718096;font-size:9px;letter-spacing:.8px;text-transform:uppercase;font-weight:750;padding:10px 9px;border-bottom:1px solid var(--line);white-space:nowrap}}td{{padding:10px 9px;border-bottom:1px solid #eff2f6;vertical-align:middle}}tbody tr:last-child td{{border-bottom:0}}.subcell{{display:block;color:var(--muted);font-size:9px;margin-top:2px;overflow-wrap:anywhere}}.empty{{text-align:center;color:var(--muted);padding:18px}}
.full-panel{{margin-bottom:17px}}.reason-tags{{display:flex;flex-wrap:wrap;gap:7px;margin-top:5px}}.reason-tag{{background:#f0f4f9;color:#43536a;border:1px solid #e3e9f1;padding:6px 9px;border-radius:7px;font-size:10px}}
.footer{{display:flex;justify-content:space-between;gap:14px;border-top:1px solid var(--line);padding-top:16px;margin-top:24px;color:var(--muted);font-size:9px}}.demo-stamp{{font-weight:850;color:#b45309;letter-spacing:1px}}
.muted{{color:var(--muted)}}.empty-panel{{font-size:12px;color:var(--muted);padding:12px 0}}
@media(max-width:760px){{.page{{margin:12px auto;padding:0 9px 18px}}.topbar,.body{{padding:20px}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.grid-2{{grid-template-columns:1fr}}.applicant-row{{flex-direction:column}}.decision-panel{{width:100%;justify-content:space-between}}.decision-copy{{text-align:left}}}}
@media print{{@page{{size:A4;margin:12mm}}body{{background:#fff}}.page{{max-width:none;margin:0;padding:0}}.report{{border:0;border-radius:0;box-shadow:none}}.topbar{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}.metric,.panel,.decision-banner,.pill{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}.panel,.metric{{break-inside:avoid}}.table-wrap{{overflow:visible}}}}
</style>
</head>
<body><main class="page"><article class="report">
<header class="topbar"><div class="brand"><div class="mark">AI</div><div><div class="brand-name">UWflow</div><div class="brand-sub">Automated underwriting decision</div></div></div><div class="top-meta"><strong>{_safe(result.get('engine_version'))}</strong>Policy {_safe(result.get('policy_version'))}<br>Generated {_safe(_date(result.get('decision_timestamp')))}</div></header>
<div class="body">
<section class="applicant-row"><div><div class="eyebrow">Applicant</div><div class="applicant-name">{_safe(result.get('applicant_display_name'))}</div><div class="applicant-id">Application {_safe(result.get('application_id'))} · Decision {_safe(result.get('decision_reference'))}</div></div><div class="decision-panel"><div class="decision-copy"><strong>{_safe(decision_label)}</strong><span>{_safe(narrative)}</span></div><span class="pill {decision_class}">{_safe(decision)}</span></div></section>
<section class="metrics">{metric_html}</section>
<section class="decision-banner {decision_class}"><div class="pill {decision_class}">{_safe(decision)}</div><div><strong>Underwriting outcome</strong><p>{_safe(narrative)} This is a synthetic demonstration result, not a real credit decision or offer.</p></div></section>
<div class="grid-2"><section class="panel"><h2 class="section-title">AIDflow profile inputs <small>10 standardized scores · Scale 0–100</small></h2>{score_html}</section><section class="panel"><h2 class="section-title">Affordability assessment <small>{_safe(currency)}</small></h2>{affordability_html}</section></div>
<div class="grid-2"><section class="panel"><h2 class="section-title">Bureau assessment</h2>{bureau_html}</section><section class="panel"><h2 class="section-title">Decision factors</h2><ul style="margin:0;padding-left:18px;font-size:12px">{factor_html}</ul><div class="eyebrow" style="margin-top:16px">Reason codes</div><div class="reason-tags">{reason_html}</div></section></div>
<section class="panel full-panel"><h2 class="section-title">Alternative-data & verification sources <small>{len(source_rows)} responses</small></h2><div class="table-wrap"><table><thead><tr><th>Source / provider</th><th>Purpose</th><th>Status</th><th>Result</th><th>Latency</th></tr></thead><tbody>{source_table}</tbody></table></div></section>
<section class="panel full-panel"><h2 class="section-title">Policy checks</h2><div class="table-wrap"><table><thead><tr><th>Check</th><th>Outcome</th><th>Detail</th></tr></thead><tbody>{policy_table}</tbody></table></div></section>
<section class="panel full-panel"><h2 class="section-title">Runtime provenance <small>Code integrity & release identity</small></h2>{runtime_provenance_html}</section>
<section class="panel full-panel"><h2 class="section-title">Decision audit trail <small>{len(audit_events)} events</small></h2><div class="table-wrap"><table><thead><tr><th>Timestamp</th><th>Event</th><th>Status</th></tr></thead><tbody>{audit_rows}</tbody></table></div></section>
<footer class="footer"><div><span class="demo-stamp">SYNTHETIC DEMO ONLY</span><br>All bureau and alternative-data responses are simulated. No real provider or credit bureau was queried.</div><div style="text-align:right">UWflow Underwriting · {_safe(result.get('decision_reference'))}<br>Currency: {_safe(currency)} · Not for lending use</div></footer>
</div></article></main></body></html>'''


def _pdf_status_color(status: Any):
    from reportlab.lib import colors
    key = _s(status, "").upper()
    if key in {"APPROVED", "PASS", "SUCCESS", "CLEAR", "FINAL"}:
        return colors.HexColor("#16804A")
    if key in {"COUNTEROFFER"}:
        return colors.HexColor("#2563EB")
    if key in {"REFER", "REVIEW", "PENDING_MANUAL_REVIEW"}:
        return colors.HexColor("#A86408")
    if key in {"DECLINED", "DECLINE", "FAIL", "ALERT"}:
        return colors.HexColor("#B42332")
    return colors.HexColor("#65758B")


def render_pdf(result: dict[str, Any], output_path: str | Path) -> Path:
    """Render a clean, paginated PDF report using ReportLab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            KeepTogether,
        )
    except ImportError as exc:  # pragma: no cover - exercised in environments without optional PDF dependency
        raise RuntimeError("PDF generation requires ReportLab. Install requirements.txt or the reportlab package.") from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    currency = _s(result.get("currency"), "EUR")
    decision = _s(result.get("decision"), "REFER").upper()
    decision_label, narrative, _ = _decision_text(result)
    affordability = result.get("affordability") or {}
    bureau = result.get("bureau_assessment") or {}
    aidflow_scoring = result.get("aidflow_scoring") or {}
    profile_inputs = aidflow_scoring.get("input_scores") or []
    source_rows = _source_rows(result)
    policy_checks = result.get("policy_checks") or []
    audit_events = result.get("audit_events") or []
    runtime_provenance = result.get("runtime_provenance") or {}
    factors = result.get("principal_decision_factors") or []
    reasons = result.get("reason_codes") or []

    navy = colors.HexColor("#101D32")
    ink = colors.HexColor("#142033")
    muted = colors.HexColor("#65758B")
    line = colors.HexColor("#E3E9F1")
    light = colors.HexColor("#F4F7FB")
    white = colors.white

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="Brand",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=23,
        leading=26,
        textColor=white,
        alignment=TA_LEFT,
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="BrandSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#C6D3E3"),
        tracking=1.0,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["Normal"], fontSize=7.5, leading=10, textColor=muted))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=12, textColor=navy, spaceBefore=7, spaceAfter=5))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=8.2, leading=11, textColor=ink))
    styles.add(ParagraphStyle(name="BodyMuted", parent=styles["BodyText"], fontSize=7.5, leading=10, textColor=muted))
    styles.add(ParagraphStyle(name="Cell", parent=styles["BodyText"], fontSize=7.1, leading=9, textColor=ink))
    styles.add(ParagraphStyle(name="CellMuted", parent=styles["BodyText"], fontSize=6.5, leading=8, textColor=muted))
    styles.add(ParagraphStyle(name="MetricLabel", parent=styles["Normal"], fontSize=6.5, leading=8, textColor=muted, uppercase=True))
    styles.add(ParagraphStyle(name="MetricValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=ink))
    styles.add(ParagraphStyle(name="TinyWhite", parent=styles["Normal"], fontSize=7, leading=9, textColor=white, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="TinyRight", parent=styles["Normal"], fontSize=7, leading=9, textColor=muted, alignment=TA_RIGHT))

    def p(value: Any, style: str = "BodySmall") -> Paragraph:
        return Paragraph(escape(_s(value, "—")), styles[style])

    def cell(value: Any) -> Paragraph:
        return Paragraph(escape(_s(value, "—")), styles["Cell"])

    def section(title: str):
        return Paragraph(escape(title), styles["Section"])

    def card_table(items: list[tuple[str, str]], widths: list[float]) -> Table:
        data = [[Paragraph(escape(label.upper()), styles["MetricLabel"]) for label, _ in items],
                [Paragraph(escape(value), styles["MetricValue"]) for _, value in items]]
        table = Table(data, colWidths=widths, rowHeights=[15, 28])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), light),
            ("BOX", (0, 0), (-1, -1), 0.5, line),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, white),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return table

    page_width, _ = A4
    content_width = page_width - 32 * mm
    story: list[Any] = []

    # Dark branded report header.
    brand_block = [Paragraph("UWflow", styles["Brand"]), Paragraph("AUTOMATED UNDERWRITING DECISION", styles["BrandSub"])]
    right_block = [Paragraph(escape(decision_label), ParagraphStyle("DecisionPill", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=white, alignment=TA_RIGHT)),
                   Paragraph(f"{escape(_s(result.get('engine_version')))}<br/>Policy {escape(_s(result.get('policy_version')))}", styles["TinyWhite"])]
    header = Table([[brand_block, right_block]], colWidths=[content_width * 0.65, content_width * 0.35])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), navy),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 13),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
    ]))
    story.extend([header, Spacer(1, 9)])

    profile = Table([
        [Paragraph("APPLICANT", styles["MetricLabel"]), Paragraph("APPLICATION / DECISION REFERENCE", styles["MetricLabel"]), Paragraph("DECISION TIMESTAMP", styles["MetricLabel"])],
        [Paragraph(f"<b>{escape(_s(result.get('applicant_display_name')))}</b>", styles["BodySmall"]),
         Paragraph(f"{escape(_s(result.get('application_id')))}<br/>{escape(_s(result.get('decision_reference')))}", styles["BodySmall"]),
         Paragraph(escape(_date(result.get("decision_timestamp"))), styles["BodySmall"])],
    ], colWidths=[content_width * .33, content_width * .34, content_width * .33])
    profile.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")), ("BOX", (0, 0), (-1, -1), .5, line),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([profile, Spacer(1, 9)])

    metrics = [
        ("Complex profile score", f"{int(result['complex_customer_profile_score'])} / 900" if result.get("complex_customer_profile_score") is not None else "Not scored"),
        ("Risk tier", _pretty(result.get("risk_tier"))),
        ("Approved amount", _money(result.get("approved_amount", 0), currency)),
        ("Offered APR", _pct(result.get("offered_apr_percent", result.get("indicative_apr_percent")), already_percent=True, decimals=2)),
    ]
    story.append(card_table(metrics, [content_width / 4] * 4))
    story.append(Spacer(1, 9))

    outcome_bg = {"APPROVED": colors.HexColor("#EAF7EF"), "COUNTEROFFER": colors.HexColor("#EDF3FF"), "REFER": colors.HexColor("#FFF6E5"), "DECLINED": colors.HexColor("#FDEEEF")}.get(decision, light)
    outcome_table = Table([[Paragraph(f"<b>{escape(decision_label)}</b><br/>{escape(narrative)}", styles["BodySmall"])]], colWidths=[content_width])
    outcome_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), outcome_bg), ("BOX", (0, 0), (-1, -1), .6, line),
        ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.extend([outcome_table, section("AIDflow complex customer-profile inference")])

    score_rows = [[cell("AIDflow profile input"), cell("Input score"), cell("Weight"), cell("Weighted contribution")]]
    for item in profile_inputs:
        score_rows.append([
            cell(item.get("source_name", item.get("source_id"))),
            cell(f"{_num(item.get('input_score_0_100')):.1f} / 100"),
            cell(_pct(item.get("weight"))),
            cell(f"{_num(item.get('weighted_contribution')):.2f}"),
        ])
    if len(score_rows) == 1:
        score_rows.append([cell("Profile score not available"), cell("—"), cell("—"), cell("—")])
    score_table = Table(score_rows, colWidths=[content_width*.42, content_width*.18, content_width*.14, content_width*.26], repeatRows=1)
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), light), ("TEXTCOLOR", (0, 0), (-1, 0), muted),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), .4, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    affordability_rows = [[cell("Affordability metric"), cell("Value")]]
    if affordability:
        aff_fields = [
            ("Gross monthly income", _money(affordability.get("monthly_income_used"), currency)),
            ("Existing monthly debt", _money(affordability.get("existing_monthly_debt_payments_used"), currency)),
            ("Housing cost", _money(affordability.get("monthly_housing_cost"), currency)),
            ("Proposed instalment", _money(affordability.get("proposed_monthly_installment"), currency)),
            ("Post-offer DTI", _pct(affordability.get("post_offer_dti"))),
            ("Residual income", _money(affordability.get("residual_income_after_debt_housing_and_offer"), currency)),
        ]
        affordability_rows.extend([[cell(label), cell(value)] for label, value in aff_fields])
    else:
        affordability_rows.append([cell("Not calculated"), cell("Manual review / early stop")])
    aff_table = Table(affordability_rows, colWidths=[content_width*.68, content_width*.32], repeatRows=1)
    aff_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), light), ("GRID", (0, 0), (-1, -1), .4, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    story.extend([
        score_table,
        Spacer(1, 7),
        section("Affordability assessment"),
        aff_table,
        section("Bureau & decision rationale"),
    ])

    bureau_data = [
        ("Bureau status", _pretty(bureau.get("decision_status", bureau.get("status")))),
        ("Bureau score", _s(bureau.get("bureau_score"))),
        ("Active delinquencies", _s(bureau.get("active_delinquencies"))),
        ("Revolving utilisation", _pct(bureau.get("revolving_utilization"))),
        ("Recent enquiries · 6m", _s(bureau.get("recent_inquiries_6m"))),
    ]
    rationale_text = "<br/>".join(f"• {escape(_reason(code))}" for code in (factors or reasons)) or "No additional decision factors supplied."
    bureau_table = Table([
        [cell("Bureau status"), cell(bureau_data[0][1]), cell("Bureau score"), cell(bureau_data[1][1])],
        [cell("Active delinquencies"), cell(bureau_data[2][1]), cell("Revolving utilisation"), cell(bureau_data[3][1])],
        [cell("Recent enquiries · 6m"), cell(bureau_data[4][1]), cell("Decision rationale"), Paragraph(rationale_text, styles["Cell"])],
    ], colWidths=[content_width*.18, content_width*.24, content_width*.18, content_width*.40])
    bureau_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), light), ("BACKGROUND", (2, 0), (2, -1), light),
        ("GRID", (0, 0), (-1, -1), .4, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(bureau_table)

    source_data = [[cell("Source"), cell("Purpose"), cell("Status"), cell("Result"), cell("Latency")]]
    for source in source_rows:
        signal = source.get("profile_input_score")
        result_value = f"Profile input {_num(signal):.1f}/100" if signal is not None else _pretty(source.get("risk_level", source.get("coverage", source.get("status"))))
        source_data.append([
            cell(source.get("source_name", source.get("source_id"))),
            cell(ROLE_LABELS.get(_s(source.get("source_role")), _pretty(source.get("source_role")))),
            cell(_pretty(source.get("status"))),
            cell(result_value),
            cell(f"{_s(source.get('latency_ms'), '—')} ms"),
        ])
    if len(source_data) == 1:
        source_data.append([cell("No alternative-data requests"), cell("—"), cell("SKIPPED"), cell("No provider calls were made"), cell("—")])
    source_table = Table(source_data, colWidths=[content_width*.33, content_width*.20, content_width*.14, content_width*.20, content_width*.13], repeatRows=1)
    source_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), light), ("GRID", (0, 0), (-1, -1), .35, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.extend([
        KeepTogether([section(f"Alternative data & verification sources ({len(source_rows)})"), source_table]),
        section("Offer structure & governance"),
    ])

    offer_data = [[cell("Offer parameter"), cell("Value"), cell("Offer parameter"), cell("Value")]]
    offer_items = [
        ("Requested principal", _money(result.get("requested_amount"), currency)),
        ("Approved principal", _money(result.get("approved_amount", 0), currency)),
        ("Loan term", f"{_s(result.get('loan_term_months'))} months" if result.get("loan_term_months") is not None else "Not set"),
        ("Offered / indicative APR", _pct(result.get("offered_apr_percent", result.get("indicative_apr_percent")), already_percent=True, decimals=2)),
        ("Monthly instalment", _money(result.get("monthly_installment"), currency)),
        ("Total repayment", _money(result.get("total_repayment"), currency)),
        ("Total interest", _money(result.get("total_interest"), currency)),
        ("AIDflow input coverage", f"{_s(aidflow_scoring.get('input_score_count', 0))} / {_s(aidflow_scoring.get('expected_input_count', 10))}"),
    ]
    for index in range(0, len(offer_items), 2):
        left = offer_items[index]
        right = offer_items[index + 1] if index + 1 < len(offer_items) else ("", "")
        offer_data.append([cell(left[0]), cell(left[1]), cell(right[0]), cell(right[1])])
    offer_table = Table(offer_data, colWidths=[content_width*.22, content_width*.28, content_width*.22, content_width*.28])
    offer_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), light),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F8FAFC")),
        ("BACKGROUND", (2, 1), (2, -1), colors.HexColor("#F8FAFC")),
        ("GRID", (0, 0), (-1, -1), .4, line), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([offer_table, section("Model governance & data-use boundaries")])

    governance = result.get("model_governance") or {}
    governance_lines = [
        "AIDflow is a dedicated scoring / inference component. It consumes ten normalized source scores and returns one complex customer-profile score.",
        "UWflow owns hard gates, bureau policy, affordability, pricing, manual-review routing and the final underwriting decision.",
        f"AIDflow score used by UWflow policy: {'Yes' if governance.get('score_used_for_underwriting') else 'No / not scored'}.",
        "This score is synthetic demo output, not a validated creditworthiness model. Real use requires legal-basis, consent, data-minimization, feature-suitability, proxy-risk, fairness and model-validation work.",
    ]
    governance_paragraph = Paragraph("<br/>".join("• " + escape(item) for item in governance_lines), styles["BodySmall"])
    governance_table = Table([[governance_paragraph]], colWidths=[content_width])
    governance_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), light), ("BOX", (0, 0), (-1, -1), .5, line),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([governance_table, section("Runtime provenance")])
    manifest_hash = _s(runtime_provenance.get("release_manifest_sha256"), "Not attached")
    task_image = _s(runtime_provenance.get("python_task_image"), "Not attached")
    if "@sha256:" in task_image:
        image_name, image_digest = task_image.split("@sha256:", 1)
        task_image = f"{image_name.rsplit('/', 1)[-1]} · {image_digest[:12]}…"
    release_identity = (
        f"{_s(runtime_provenance.get('runtime_release'), 'Local / unversioned')} "
        f"({_s(runtime_provenance.get('source_ref'), 'no source ref')})"
    )
    integrity_identity = (
        f"{_s(runtime_provenance.get('integrity_status'), 'NOT VERIFIED')} · "
        f"{_s(runtime_provenance.get('runtime_file_count'), '—')} modules"
    )
    execution_identity = (
        f"{_s(runtime_provenance.get('task_runner'), 'Not attached')} · "
        f"Py {_s(runtime_provenance.get('python_version'), '—')} · {task_image}"
    )
    # Keep the PDF cell compact; the full digest remains in JSON and Kestra outputs.
    manifest_hash = f"{manifest_hash[:16]}…" if len(manifest_hash) > 20 else manifest_hash
    runtime_data = [
        [cell("Runtime release / source"), cell("Integrity"), cell("Execution runtime"), cell("Manifest SHA-256")],
        [cell(release_identity), cell(integrity_identity), cell(execution_identity), cell(manifest_hash)],
    ]
    runtime_table = Table(runtime_data, colWidths=[content_width*.20, content_width*.17, content_width*.37, content_width*.22], repeatRows=1)
    runtime_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), light), ("GRID", (0, 0), (-1, -1), .35, line),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
    ]))
    story.extend([runtime_table, section("Policy checks")])
    policy_data = [[cell("Policy check"), cell("Status"), cell("Detail")]]
    for check in policy_checks:
        detail = _policy_detail(check, currency)
        policy_data.append([cell(_pretty(check.get("check_id"))), cell(_pretty(check.get("status"))), cell(detail)])
    if len(policy_data) == 1:
        policy_data.append([cell("No policy checks"), cell("—"), cell("—")])
    policy_table = Table(policy_data, colWidths=[content_width*.32, content_width*.15, content_width*.53], repeatRows=1)
    policy_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), light), ("GRID", (0, 0), (-1, -1), .35, line),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([policy_table, Spacer(1, 3)])

    # Compact two-column timeline keeps the complete event history together
    # without pushing the final events and disclaimer onto an almost-empty page.
    audit_style = ParagraphStyle(
        name="AuditCompact",
        parent=styles["CellMuted"],
        fontSize=6.3,
        leading=7.4,
        textColor=ink,
    )
    audit_cells = []
    for event in audit_events:
        timestamp = escape(_date(event.get("timestamp")))
        event_name = escape(_pretty(event.get("event")))
        status = escape(_pretty(event.get("status")))
        audit_cells.append(Paragraph(
            f"<b>{timestamp}</b> · {event_name} · <b>{status}</b>",
            audit_style,
        ))
    if not audit_cells:
        audit_cells.append(Paragraph("No audit events", audit_style))
    audit_data = []
    for index in range(0, len(audit_cells), 2):
        right_cell = audit_cells[index + 1] if index + 1 < len(audit_cells) else ""
        audit_data.append([audit_cells[index], right_cell])
    audit_table = Table(
        audit_data,
        colWidths=[content_width * .5, content_width * .5],
        hAlign="LEFT",
    )
    audit_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), light),
        ("GRID", (0, 0), (-1, -1), .35, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    disclaimer = Paragraph(
        "<b>SYNTHETIC DEMO ONLY</b> — All bureau and alternative-data responses are simulated. "
        "This scorecard is not validated for credit decisions and must not be used to approve, decline, price or otherwise affect a real applicant.",
        styles["BodyMuted"]
    )
    story.extend([
        section("Decision audit trail"),
        audit_table,
        Spacer(1, 4),
        disclaimer,
    ])

    def page_decor(canvas, doc):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(line)
        canvas.setLineWidth(.5)
        canvas.line(16 * mm, 12 * mm, width - 16 * mm, 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(16 * mm, 7.5 * mm, "UWflow · SYNTHETIC DEMO ONLY · NOT FOR LENDING USE")
        canvas.drawRightString(width - 16 * mm, 7.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(output), pagesize=A4,
        rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=10 * mm, bottomMargin=14 * mm,
        title=f"UWflow Underwriting Decision {_s(result.get('decision_reference'))}",
        author="UWflow Demonstration",
        subject="Synthetic underwriting decision report",
    )
    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    return output


def generate_reports(result: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    """Write JSON, HTML and PDF reports to ``output_dir``."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "underwriting_decision.json"
    html_path = target / "underwriting_decision.html"
    pdf_path = target / "underwriting_decision.pdf"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(result), encoding="utf-8")
    render_pdf(result, pdf_path)
    return {"json": json_path, "html": html_path, "pdf": pdf_path}
