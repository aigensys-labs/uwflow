"""Shared pytest fixtures and repository-root configuration."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def copy_isolated_repository(destination: Path) -> Path:
    """Copy source into a temporary checkout without generated or local state."""
    ignore = shutil.ignore_patterns(
        ".git",
        "venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        "dist",
        "build",
        "*.egg-info",
        ".eggs",
        "*.egg",
        "*.whl",
        ".tox",
        ".nox",
        ".DS_Store",
        "cache",
        "reports",
        "data",
        "operator-state",
    )
    shutil.copytree(PROJECT_ROOT, destination, ignore=ignore)
    return destination


@pytest.fixture
def isolated_repository(tmp_path: Path) -> Path:
    return copy_isolated_repository(tmp_path / "uwflow-isolated")


@pytest.fixture
def candidate_package(isolated_repository: Path) -> dict:
    """Build a real candidate inside a temporary checkout, never in the package."""
    from modules.lifecycle.tools.dev_candidate import build_dev_candidate

    result = build_dev_candidate(isolated_repository, baseline_release="2.0.0")
    return {
        "root": isolated_repository,
        "result": result,
        "candidate_id": result["candidate_id"],
    }


@pytest.fixture
def replay_package(candidate_package: dict) -> dict:
    """Build a current paired-replay flow and its History bundle in temporary state."""
    from modules.evaluation.tools.history_replay_flow import build_flow

    root = candidate_package["root"]
    candidate_id = candidate_package["candidate_id"]
    flow_path = build_flow(candidate_id, baseline_release="2.0.0", repository_root=root)
    flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    labels = flow["labels"]
    return {
        **candidate_package,
        "flow_path": flow_path,
        "flow": flow,
        "flow_id": flow["id"],
        "history_tools_id": labels["history-tools-bundle"],
    }
