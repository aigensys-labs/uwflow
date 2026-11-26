"""Tests for Python module and public API docstring coverage."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("core", "modules", "tools", "tests")
IMMUTABLE_RUNTIME_ROOTS = (
    Path("core/python/runtime"),
    Path("core/kestra/namespace-files/runtime/releases"),
)


def _is_immutable_runtime(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return any(relative.is_relative_to(root) for root in IMMUTABLE_RUNTIME_ROOTS)


def test_every_python_module_has_a_module_docstring() -> None:
    """Require a purpose statement in every source, test and versioned runtime module."""
    missing: list[str] = []
    for root in SOURCE_ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if ast.get_docstring(tree) is None:
                missing.append(str(path.relative_to(ROOT)))

    assert not missing, "Python modules without a module docstring:\n" + "\n".join(missing)


def test_current_public_source_apis_have_docstrings() -> None:
    """Document public source functions, classes and class methods outside the immutable runtime."""
    missing: list[str] = []
    for root in ("core", "modules", "tools"):
        for path in (ROOT / root).rglob("*.py"):
            if _is_immutable_runtime(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name.startswith("_"):
                        continue
                    if ast.get_docstring(node) is None:
                        missing.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
                    if isinstance(node, ast.ClassDef):
                        for method in node.body:
                            if (
                                isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and not method.name.startswith("_")
                                and ast.get_docstring(method) is None
                            ):
                                missing.append(
                                    f"{path.relative_to(ROOT)}:{method.lineno}:"
                                    f"{node.name}.{method.name}"
                                )

    assert not missing, "Public APIs without docstrings:\n" + "\n".join(missing)


def test_ruff_formatting_contract_is_reproducible() -> None:
    """Keep formatter settings pinned and run quality gates outside the user Fast Route."""
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff = pyproject["tool"]["ruff"]
    formatting = ruff["format"]
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    repository_check = (ROOT / "tools/guides/workflow/22-verify-repository.sh").read_text(
        encoding="utf-8"
    )
    fast_route_setup = (ROOT / "tools/guides/workflow/01-python-environment.sh").read_text(
        encoding="utf-8"
    )

    assert "ruff==0.17.6" in dev_dependencies
    assert ruff["line-length"] == 100
    assert formatting["quote-style"] == "double"
    assert formatting["indent-style"] == "space"
    assert formatting["line-ending"] == "lf"
    for command in ("ruff format --check", "ruff check"):
        assert command in ci
        assert command in repository_check
        assert command not in fast_route_setup
