"""Shared utilities for the synthetic UWflow underwriting demonstration."""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from typing import Any

DEMO_MODE = "SYNTHETIC_DEMO_ONLY"
POLICY_VERSION = "UW-DEMO-POLICY-1.1-EUR"
UWFLOW_VERSION = "UWFLOW-UNDERWRITING-1.2-EUR"

# Demonstration product policy amounts are denominated in EUR.
# These thresholds are re-denominated from the original CZK demo policy;
# they are illustrative values, not regulatory or lender policy limits.
SUPPORTED_CURRENCY = "EUR"
MIN_MONTHLY_INCOME = 655.54       # Original CZK 16,000
MIN_REQUEST_AMOUNT = 1229.13      # Original CZK 30,000
MAX_REQUEST_AMOUNT = 40971.00     # Original CZK 1,000,000
MIN_OFFER_AMOUNT = 1229.13        # Original CZK 30,000
MAX_OFFER_AMOUNT = 40971.00       # Original CZK 1,000,000
MIN_RESIDUAL_INCOME = 491.65      # Original CZK 12,000


def stable_rng(*parts: object) -> random.Random:
    """Return a deterministic RNG, stable across Python processes and runs."""
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(seed)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_float(value: Any, field: str, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return result


def safe_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    try:
        # Reject non-integral floats rather than silently truncating them.
        numeric = float(value)
        if not numeric.is_integer():
            raise ValueError
        result = int(numeric)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return result
