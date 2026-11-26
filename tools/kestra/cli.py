"""Small command builders for safe, predictable kestractl invocations."""

from __future__ import annotations

import shlex


def nsfiles_upload_directory_command(
    namespace: str,
    local_directory: str,
    namespace_path: str,
    *,
    allow_missing_namespace: bool = True,
    fail_fast: bool = True,
) -> str:
    """Build a directory upload that places contents directly at namespace_path.

    kestractl's default directory-upload behavior nests the source directory's
    basename beneath the destination. UWflow destinations already contain the
    release/candidate identifier, so every such upload must pass ``--no-root``.
    """
    parts = [
        "kestractl",
        "nsfiles",
        "upload",
        namespace,
        local_directory,
        namespace_path,
        "--no-root",
    ]
    if fail_fast:
        parts.append("--fail-fast")
    if allow_missing_namespace:
        parts.append("--allow-missing-namespace")
    return " ".join(shlex.quote(part) for part in parts)
