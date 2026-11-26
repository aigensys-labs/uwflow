"""Generated UWflow policy functions. DO NOT EDIT BY HAND.

Regenerate with: python tools/compile_policy_spec.py
"""
from __future__ import annotations

import math
from typing import Any, Mapping

POLICY_METADATA = {'stage_1_hard_gates': {'policy_id': 'stage1_hard_gates_v1', 'kind': 'dmn_table', 'sha256': 'bc0a5eed7f1265f89fead869a7508e865be54b7a4c70c573698c864351a4ee6f'}, 'stage_3_source_plan': {'policy_id': 'stage3_consented_source_plan_v1', 'kind': 'routing_dag', 'sha256': '0305637e2cb7b5cac4d7e1cc6b72915824e98eb01af6dd2ca6ce50e89f37d500'}}
_STAGE1_INPUT_TYPES = {'validation_error_count': 'integer', 'applicant_age': 'integer', 'monthly_income': 'number', 'employment_status': 'string', 'requested_amount': 'number', 'loan_term_months': 'integer'}


def _validate_context(context: Mapping[str, Any], input_types: dict[str, str]) -> None:
    """Fail closed when a required, typed policy input is unavailable."""
    for field, field_type in input_types.items():
        if field not in context:
            raise ValueError(f"Missing policy input: {field}")
        value = context[field]
        valid = (
            isinstance(value, bool) if field_type == 'boolean' else
            isinstance(value, int) and not isinstance(value, bool) if field_type == 'integer' else
            isinstance(value, (int, float)) and not isinstance(value, bool) if field_type == 'number' else
            isinstance(value, str) if field_type == 'string' else
            False
        )
        if not valid:
            raise ValueError(f"Policy input {field!r} must be {field_type}")


def _matches(context: Mapping[str, Any], condition: dict[str, Any]) -> bool:
    """Evaluate one previously validated condition AST node."""
    actual = context[condition['field']]
    expected = condition['value']
    op = condition['op']
    if op == '==':
        return actual == expected
    if op == '!=':
        return actual != expected
    if op == '<':
        return actual < expected
    if op == '<=':
        return actual <= expected
    if op == '>':
        return actual > expected
    if op == '>=':
        return actual >= expected
    if op == 'in':
        return actual in expected
    if op == 'between':
        return expected[0] <= actual <= expected[1]
    raise ValueError(f"Unsupported compiled operator: {op!r}")


_STAGE1_CHECKS = [{'check_id': 'APPLICATION_DATA_VALID', 'field': 'validation_error_count', 'description': 'Required fields, numeric ranges and supported product parameters are valid', 'valid_when': {'op': '==', 'value': 0}, 'failure_reason_code': 'INVALID_APPLICATION_DATA'}, {'check_id': 'MINIMUM_AGE', 'field': 'applicant_age', 'description': 'Applicant age must be between 18 and 75 inclusive', 'valid_when': {'op': 'between', 'value': [18, 75]}, 'failure_reason_code': 'AGE_OUT_OF_POLICY'}, {'check_id': 'MINIMUM_INCOME', 'field': 'monthly_income', 'description': 'Verified gross monthly income must be at least EUR 655.54', 'valid_when': {'op': '>=', 'value': 655.54}, 'failure_reason_code': 'INCOME_BELOW_POLICY_FLOOR'}, {'check_id': 'EMPLOYMENT_STATUS', 'field': 'employment_status', 'description': "Unemployed applicants do not meet this demo product's eligibility policy", 'valid_when': {'op': 'in', 'value': ['FULL_TIME', 'PART_TIME', 'SELF_EMPLOYED', 'FIXED_TERM']}, 'failure_reason_code': 'UNEMPLOYED_STATUS'}, {'check_id': 'REQUEST_AMOUNT', 'field': 'requested_amount', 'description': 'Requested principal must be between EUR 1,229.13 and EUR 40,971.00', 'valid_when': {'op': 'between', 'value': [1229.13, 40971.0]}, 'failure_reason_code': 'REQUEST_AMOUNT_OUT_OF_RANGE'}, {'check_id': 'LOAN_TERM', 'field': 'loan_term_months', 'description': 'Requested term must be one of 12, 24, 36, 48, 60, 72 or 84 months', 'valid_when': {'op': 'in', 'value': [12, 24, 36, 48, 60, 72, 84]}, 'failure_reason_code': 'UNSUPPORTED_LOAN_TERM'}]

def evaluate_stage1_hard_gates(context: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one positive predicate per Stage 1 underwriting variable.

    A true predicate produces PASS. Its logical complement produces FAIL
    with the check's configured failure reason code.
    """
    _validate_context(context, _STAGE1_INPUT_TYPES)
    checks: list[dict[str, Any]] = []
    trace: list[str] = []
    for check in _STAGE1_CHECKS:
        condition = {'field': check['field'], **check['valid_when']}
        passed = _matches(context, condition)
        checks.append({
            'check_id': check['check_id'],
            'status': 'PASS' if passed else 'FAIL',
            'reason_code': None if passed else check['failure_reason_code'],
            'description': check['description'],
        })
        trace.append(check['check_id'])
    return {'checks': checks, 'trace': trace}

_STAGE3_INPUT_TYPES = {'hard_gates_passed': 'boolean', 'bureau_decision_status': 'string', 'data_sharing_consent': 'boolean'}

def _route_n_hard_gates(context: Mapping[str, Any], trace: list[str]) -> dict[str, Any]:
    trace.append('n_hard_gates')
    if _matches(context, {'field': 'hard_gates_passed', 'op': '==', 'value': True}):
        return _route_n_bureau(context, trace)
    else:
        return _route_out_skip_sources(context, trace)

def _route_n_bureau(context: Mapping[str, Any], trace: list[str]) -> dict[str, Any]:
    trace.append('n_bureau')
    if _matches(context, {'field': 'bureau_decision_status', 'op': '!=', 'value': 'DECLINE'}):
        return _route_n_consent(context, trace)
    else:
        return _route_out_skip_sources(context, trace)

def _route_n_consent(context: Mapping[str, Any], trace: list[str]) -> dict[str, Any]:
    trace.append('n_consent')
    if _matches(context, {'field': 'data_sharing_consent', 'op': '==', 'value': True}):
        return _route_out_collect_sources(context, trace)
    else:
        return _route_out_skip_sources(context, trace)

def _route_out_collect_sources(context: Mapping[str, Any], trace: list[str]) -> dict[str, Any]:
    trace.append('out_collect_sources')
    source_ids = ['telco_stability', 'utility_reliability', 'open_banking_cashflow', 'device_fingerprint', 'geo_mobility', 'ecommerce_behavior', 'digital_identity_age', 'income_velocity', 'microloan_history', 'merchant_affinity']
    return {
        'action': 'COLLECT_SOURCES',
        'source_ids': list(source_ids),
        'loop_values': list(source_ids) if source_ids else ['__NO_SOURCE_COLLECTION__'],
        'planned_count': len(source_ids),
        'reason': 'CONSENTED_SOURCE_COLLECTION',
        'trace': list(trace),
    }

def _route_out_skip_sources(context: Mapping[str, Any], trace: list[str]) -> dict[str, Any]:
    trace.append('out_skip_sources')
    return {
        'action': 'SKIP_SOURCE_COLLECTION',
        'source_ids': [],
        'loop_values': ['__NO_SOURCE_COLLECTION__'],
        'planned_count': 0,
        'reason': 'SOURCE_COLLECTION_NOT_PERMITTED_OR_NOT_REQUIRED',
        'trace': list(trace),
    }

def build_stage3_source_plan(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return the source-collection plan; never performs source I/O."""
    _validate_context(context, _STAGE3_INPUT_TYPES)
    return _route_n_hard_gates(context, [])
