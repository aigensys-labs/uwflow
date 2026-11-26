"""Register completed champion/challenger evidence as an immutable evaluation artifact."""

from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())


class EvaluationRegistrationError(RuntimeError):
    """Raised when evaluation evidence does not match its candidate and baseline."""

    pass


def sha(data: bytes) -> str:
    """Return the SHA-256 digest of an evidence payload."""
    return hashlib.sha256(data).hexdigest()


def register_evaluation(
    repository_root: Path | str,
    evaluation_id: str,
    candidate_id: str,
    baseline_release: str,
    dataset_id: str,
    source_dir: Path | str,
) -> dict:
    """Register replay outputs as immutable evidence bound to one candidate, baseline and dataset."""
    root = Path(repository_root).resolve()
    if not re.fullmatch(r"eval-[a-z0-9][a-z0-9-]{2,60}", evaluation_id):
        raise EvaluationRegistrationError("Evaluation ID must use eval-<lowercase-id> format")
    if not re.fullmatch(r"dev-[0-9a-f]{16}", candidate_id):
        raise EvaluationRegistrationError("Invalid candidate ID")
    if not re.fullmatch(r"\d+\.\d+\.\d+", baseline_release):
        raise EvaluationRegistrationError("Baseline release must be MAJOR.MINOR.PATCH")
    if not dataset_id.strip():
        raise EvaluationRegistrationError("Dataset ID is required")
    from modules.lifecycle.workspaces import WorkspaceError, WorkspaceStore

    try:
        _, candidate_manifest, candidate_manifest_bytes = WorkspaceStore(root)._verify_candidate(
            candidate_id
        )
    except WorkspaceError as exc:
        raise EvaluationRegistrationError(
            f"Candidate is not a complete verified v2 artifact: {exc}"
        ) from exc
    if candidate_manifest.get("based_on_production_release") != baseline_release:
        raise EvaluationRegistrationError(
            "Evaluation baseline does not match the candidate's recorded parent baseline"
        )
    source = Path(source_dir).resolve()
    if not source.is_dir() or not (source / "comparison.json").is_file():
        raise EvaluationRegistrationError("Evaluation source must contain comparison.json")
    target = root / "var/artifacts/evaluations" / evaluation_id
    if target.exists():
        raise EvaluationRegistrationError("Evaluation artifact already exists and is immutable")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging)
    files = {
        p.relative_to(staging).as_posix(): sha(p.read_bytes())
        for p in sorted(staging.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "evaluation_format": 1,
        "evaluation_id": evaluation_id,
        "candidate_id": candidate_id,
        "candidate_manifest_sha256": sha(candidate_manifest_bytes),
        "baseline_release": baseline_release,
        "dataset_id": dataset_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    (staging / "evaluation-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    staging.replace(target)
    return {
        "evaluation_id": evaluation_id,
        "candidate_id": candidate_id,
        "path": target.relative_to(root).as_posix(),
        "files": len(files),
    }


def main() -> int:
    """Register a completed replay evidence directory using the command-line interface."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--baseline-release", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--source-dir", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            register_evaluation(
                ROOT,
                args.evaluation_id,
                args.candidate,
                args.baseline_release,
                args.dataset_id,
                args.source_dir,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
