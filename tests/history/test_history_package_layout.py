"""Tests for the installable History package and its source layout."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def _run_help(script: Path, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_history_replay_cli_resolves_top_level_source_package() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    script = ROOT / "tools" / "history" / "replay" / "run_batch.py"
    result = _run_help(script, cwd=ROOT, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Replay a historical dataset batch" in result.stdout


def test_history_replay_cli_resolves_virtual_namespace_files_package(tmp_path: Path) -> None:
    """The built bundle keeps scripts/uwflow_history even though source is top-level."""
    bundle = tmp_path / "history-tools" / "ht-test"
    package_target = bundle / "scripts" / "uwflow_history"
    package_target.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "modules" / "history" / "python" / "uwflow_history", package_target)

    tools_target = bundle / "tools"
    tools_target.mkdir(parents=True)
    script_target = tools_target / "run_history_batch.py"
    shutil.copy2(ROOT / "tools" / "history" / "replay" / "run_batch.py", script_target)

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = _run_help(script_target, cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Replay a historical dataset batch" in result.stdout
