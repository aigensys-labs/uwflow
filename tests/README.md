# Test suite

Tests are grouped by the system boundary they protect. Fixtures shared across groups stay
in [fixtures/](fixtures/).

| Directory | Coverage |
|---|---|
| [application/](application/) | Underwriting behavior and report generation |
| [policy/](policy/) | Policy schema, compiler, migration and Studio API |
| [history/](history/) | Dataset connectors, canonical integrity, replay and comparison |
| [kestra/](kestra/) | Task bootstrap, CLI uploads and YAML serialization safety |
| [release/](release/) | Runtime and deployment provenance |
| [repository/](repository/) | Repository contracts, candidate building and operator workflow launchers |

Install the development extras first with `python -m pip install -e ".[dev]"`. Then run
the complete suite from the repository root with `python -m pytest -q`. The same test command is used in CI. CI also checks Ruff linting and formatting, Python compilation, policy generation, immutable runtime/history bundles and source/wheel builds. The project is installed in editable mode so tests import the same declared packages and runtime modules that developer commands use; individual tests do not modify `sys.path`. A live Docker/Kestra/PostgreSQL environment is a separate integration validation and is not implied by a passing unit-test suite.
