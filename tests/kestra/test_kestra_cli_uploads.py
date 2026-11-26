"""Tests for correct Kestra Namespace Files upload paths and flags."""

from __future__ import annotations

from tools.kestra.cli import nsfiles_upload_directory_command


def test_directory_upload_suppresses_source_directory_nesting() -> None:
    command = nsfiles_upload_directory_command(
        "com.ai.credit.dev",
        "./kestra/namespace-files/runtime/releases/2.0.0",
        "runtime/releases/2.0.0",
    )
    assert command == (
        "kestractl nsfiles upload com.ai.credit.dev "
        "./kestra/namespace-files/runtime/releases/2.0.0 "
        "runtime/releases/2.0.0 --no-root --fail-fast --allow-missing-namespace"
    )


def test_candidate_and_history_destinations_keep_exact_artifact_root() -> None:
    candidate = nsfiles_upload_directory_command(
        "com.ai.credit.dev",
        "./kestra/namespace-files/runtime/candidates/dev-0123456789abcdef",
        "runtime/candidates/dev-0123456789abcdef",
    )
    history = nsfiles_upload_directory_command(
        "com.ai.credit.dev",
        "./kestra/namespace-files/history-tools/ht-0123456789abcdef",
        "history-tools/ht-0123456789abcdef",
    )
    assert "--no-root" in candidate
    assert "--no-root" in history
    assert "runtime/candidates/dev-0123456789abcdef" in candidate
    assert "history-tools/ht-0123456789abcdef" in history
