"""Canonical serialization and identifiers for immutable dataset snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_dataset_id(dataset_id: str) -> str:
    """Validate and return a canonical historical dataset identifier."""
    if not isinstance(dataset_id, str) or not _DATASET_ID_RE.fullmatch(dataset_id):
        raise ValueError("dataset_id must use only letters, digits, dot, underscore or hyphen")
    return dataset_id


def canonical_json(value: Any) -> str:
    """Serialize a value as deterministic UTF-8-compatible JSON for hashing and storage."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def update_case_digest(digest: Any, case_dict: dict[str, Any]) -> None:
    """Update a running dataset digest with one canonical historical case."""
    digest.update(canonical_json(case_dict).encode("utf-8"))
    digest.update(b"\n")


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest of a text value encoded as UTF-8."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
