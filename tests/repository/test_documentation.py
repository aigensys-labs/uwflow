"""Tests for Markdown navigation, links and documentation contracts."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def test_relative_markdown_links_resolve() -> None:
    """Keep the first-time visitor navigation usable after repository refactors."""
    excluded = {".pytest_cache", "build", "dist", "venv", "venv"}
    markdown_files = [
        path
        for path in ROOT.rglob("*.md")
        if not any(part in excluded for part in path.relative_to(ROOT).parts)
    ]

    missing: list[str] = []
    for markdown_file in markdown_files:
        content = markdown_file.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(content):
            target = match.group(1).strip()
            if not target or target.startswith("<"):
                continue
            target = target.split(maxsplit=1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target_path = Path(unquote(parsed.path))
            if not target_path.is_absolute():
                target_path = markdown_file.parent / target_path
            if not target_path.resolve().exists():
                missing.append(f"{markdown_file.relative_to(ROOT)} -> {target}")

    assert not missing, "Broken relative Markdown links:\n" + "\n".join(missing)


def test_production_release_guide_matches_current_deployment_contract() -> None:
    """Keep the end-to-end production guide aligned with the checked-in release workflow."""
    guide_path = ROOT / "docs" / "production" / "production-release-workflow.md"
    guide = guide_path.read_text(encoding="utf-8")
    deploy = (ROOT / ".github" / "workflows" / "deploy-kestra.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    flow = (ROOT / "core" / "kestra" / "flows" / "uwflow_production_underwriting.yaml").read_text(
        encoding="utf-8"
    )
    image_builder = (ROOT / "tools" / "docker" / "build-images.sh").read_text(encoding="utf-8")

    assert guide_path.is_file()
    assert "workflow_dispatch:" in deploy
    assert "var/releases/approved/" in deploy
    assert "inputs.release_id" in deploy
    assert "environment: uwflow-production" in deploy
    assert "override: false" in deploy and "override: true" in deploy
    assert "runtime/releases/${{ inputs.release_id }}" in deploy
    assert "${{ steps.release.outputs.dir }}" in deploy
    assert all(
        secret in deploy for secret in ("KESTRA_HOSTNAME", "KESTRA_USERNAME", "KESTRA_PASSWORD")
    )
    assert 'python-version: ["3.12", "3.13"]' in ci
    assert "UNDERWRITING_WEBHOOK_KEY" in flow
    assert "--push" in image_builder

    for phrase in (
        "Analyst strategy workspace",
        "var/artifacts/candidates/",
        "var/releases/approved/",
        "candidate_manifest_sha256",
        "digest-pinned OCI image reference",
        "workflow_dispatch",
        "var/deployments/production/",
        "does not deploy",
    ):
        assert phrase in guide or phrase in deploy

    assert "Production" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Governed release boundary" in (ROOT / "docs" / "README.md").read_text(encoding="utf-8")


def test_documentation_entry_points_are_task_oriented_and_unified() -> None:
    docs = ROOT / "docs"
    groups = {"development", "production", "studio", "architecture", "assets"}
    actual = {path.name for path in docs.iterdir() if path.is_dir()}
    assert actual == groups

    index = (docs / "README.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Choose your run path" in readme
    assert "## What Modules add" in readme
    assert "## Run UWflow" in index
    assert "## Operate the platform modules" in index
    assert "## Architecture and engineering" in index
    assert "Run Core only" in readme and "Run the full platform" in readme
    assert "Core first-run guide" in index

    # Module pages are the canonical landing pages for task-specific guide links.
    for module, expected_guide in (
        ("policy-studio", "policy-studio.md"),
        ("lifecycle", "policy-studio-dev.md"),
        ("history", "historical-data-and-replay.md"),
        ("evaluation", "champion-challenger-impact-report.md"),
        ("reporting", "champion-challenger-impact-report.md"),
        ("production", "production-release-workflow.md"),
    ):
        page = (ROOT / "modules" / module / "README.md").read_text(encoding="utf-8")
        assert expected_guide in page, f"{module} README is missing its operator guide link"
        assert "| Guide | Use it to… |" in page

    assert not (docs / "development" / "first-run.md").exists()
    assert not any(
        (docs / old).exists() for old in ("guides", "operations", "governance", "maintenance")
    )


def test_operational_state_documentation_defines_one_stable_var_root() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lifecycle = (ROOT / "docs/architecture/lifecycle-and-storage.md").read_text(encoding="utf-8")
    state_readme = (ROOT / "var/README.md").read_text(encoding="utf-8")
    assert "var/" in root_readme and "var/" in lifecycle
    assert "repository root" in root_readme.lower()
    assert "repository root" in lifecycle.lower()
    assert "repository root" in state_readme.lower()
    for relative in (
        "var/workspaces/strategies/",
        "var/artifacts/candidates/",
        "var/releases/approved/",
        "var/deployments/production/",
        "var/reports/",
        "var/data/history/",
        "var/operator-state/",
    ):
        assert relative in lifecycle
        assert relative in state_readme or relative.split("/", 2)[1] in state_readme


def test_workspace_release_and_deployment_documents_match_repository_contract() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    studio = (ROOT / "docs/studio/policy-studio.md").read_text(encoding="utf-8")
    compiler = (ROOT / "docs/studio/policy-studio-compiler.md").read_text(encoding="utf-8")
    publishing = (ROOT / "docs/production/github-publishing.md").read_text(encoding="utf-8")
    provenance = (ROOT / "docs/production/audit-and-provenance.md").read_text(encoding="utf-8")
    deploy = (ROOT / ".github/workflows/deploy-kestra.yml").read_text(encoding="utf-8")

    assert "var/" in root_readme
    for content in (studio, compiler):
        assert "var/workspaces/strategies/" in content
        assert "var/artifacts/candidates/" in content
        assert "var/releases/approved/" in content
    assert "Fork candidate" in studio
    assert "Fork approved release" in studio
    assert "does not allocate" in compiler or "does not calculate" in compiler
    assert "workflow_dispatch" in publishing
    assert "protected `main`" in publishing
    assert "release_id" in publishing
    assert "`approved_by` field is a supplied attestation string" in provenance
    assert "workflow_dispatch:" in deploy
    assert 'GITHUB_REF_NAME}" != "main"' in deploy
    assert "inputs.release_id" in deploy
    assert "refs/tags" not in deploy
    assert "on: push" not in deploy

    # These are obsolete deployment instructions and must not return to current docs.
    for obsolete in (
        "restrict deployments to the protected `v*` release tags",
        "tag must be `v<project.version>`",
    ):
        assert obsolete not in publishing


def test_markdown_path_links_use_plain_text_labels() -> None:
    highlighted = re.compile(r"\[`[^`]+`\]\(")
    markdown_files = [path for path in ROOT.rglob("*.md") if ".pytest_cache" not in path.parts]
    violations = [
        str(path.relative_to(ROOT))
        for path in markdown_files
        if highlighted.search(path.read_text(encoding="utf-8"))
    ]
    assert not violations, (
        "Use plain-text Markdown link labels, not inline-code labels: " + ", ".join(violations)
    )


def _fenced_blocks(markdown: str) -> list[tuple[str, str]]:
    """Return fenced Markdown blocks and reject unclosed or malformed fences."""
    blocks: list[tuple[str, str]] = []
    active: tuple[str, int, str, list[str], int] | None = None
    fence_pattern = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

    for line_number, line in enumerate(markdown.splitlines(), start=1):
        match = fence_pattern.match(line)
        if match is None:
            if active is not None:
                active[3].append(line)
            continue

        marker, suffix = match.groups()
        if active is None:
            if marker[0] == "`" and "`" in suffix:
                raise AssertionError(
                    f"Backtick fence info contains a backtick at line {line_number}"
                )
            active = (marker[0], len(marker), suffix.strip(), [], line_number)
            continue

        active_char, active_length, info, content, opening_line = active
        is_closing = (
            marker[0] == active_char and len(marker) >= active_length and not suffix.strip()
        )
        if is_closing:
            blocks.append((info, "\n".join(content)))
            active = None
        else:
            content.append(line)

    if active is not None:
        raise AssertionError(f"Unclosed Markdown fence opened at line {active[4]}")
    return blocks


def test_all_markdown_fences_are_closed_and_readme_trees_are_separate() -> None:
    markdown_files = list(ROOT.rglob("*.md"))
    for path in markdown_files:
        _fenced_blocks(path.read_text(encoding="utf-8"))

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture_section = readme.split("## Core and Modules", 1)[1].split(
        "## Choose your run path", 1
    )[0]
    blocks = _fenced_blocks(architecture_section)

    assert len(blocks) == 4
    assert blocks[0][0] == "mermaid"
    assert blocks[1][0] == "text" and "MODULES" in blocks[1][1]
    assert blocks[2][0] == "text" and "repository-root/" in blocks[2][1]
    assert blocks[3][0] == "text" and blocks[3][1].startswith("var/")
    assert "The repository root is stable" not in "\n".join(content for _, content in blocks)


def test_readme_technology_badges_match_declared_project_stack() -> None:
    """Keep README badges factual and aligned with the package declarations."""
    import json

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package = json.loads(
        (ROOT / "modules/policy-studio/frontend/package.json").read_text(encoding="utf-8")
    )
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    docker_launcher = (ROOT / "core/docker-run.sh").read_text(encoding="utf-8")

    assert 'alt="Python 3.12+"' in readme
    assert 'requires-python = ">=3.12"' in pyproject
    assert 'alt="Environment: venv and pip"' in readme
    assert 'alt="Node.js 20.19+ or 22.12+"' in readme
    assert package["engines"]["node"] == "^20.19.0 || >=22.12.0"
    assert 'alt="React 19"' in readme
    assert package["dependencies"]["react"].startswith("19.")
    assert 'alt="FastAPI"' in readme and "fastapi>=" in pyproject
    assert 'alt="Kestra 2.0.10"' in readme and "v2.0.10-slim" in docker_launcher
    assert 'alt="Docker"' in readme
    assert 'alt="Ruff 0.17.6"' in readme
    assert '"ruff==0.17.6"' in pyproject
    assert 'alt="pytest"' in readme
    assert 'alt="Core: Apache 2.0"' in readme
    assert "Apache License" in license_text
    assert 'alt="Synthetic demo only"' in readme

    # Do not advertise tools or frameworks that this package does not use.
    for unsupported in ('alt="uv"', 'alt="Black"', 'alt="MCP"', 'alt="Temporal"'):
        assert unsupported not in readme
