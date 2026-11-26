# Contributing

Thank you for considering a contribution to UWflow. This repository is a
synthetic demonstration; contributions must preserve the demo-only boundary and
must not introduce real applicant information, credentials or production data.

## Development setup and checks

Python 3.12 or newer with the standard `venv` module is required. Open a Bash terminal directly in the repository root
(the folder containing `pyproject.toml`) and run the same checked environment setup used by
the operator guides:

```bash
git clone https://github.com/aigensys-labs/uwflow.git
cd uwflow
bash tools/guides/workflow/01-python-environment.sh
```

This creates `var/venv`, reuses a valid environment, or repairs an incomplete one before it installs the editable project and development extras, then runs
the test suite, verifies generated policy/runtime/history bundles and checks the Starlette
`TestClient` transport dependency. The check is intentionally strict: a deprecation warning
from the supported test-client import is a dependency-compatibility issue to resolve, not a
warning to suppress.

Generated reports and local `.env` files are ignored by Git. Never attach real
credit reports, identity documents, bank statements, credentials or production
payloads to issues or pull requests.

The tests follow the same responsibility map as the source tree. See [tests/README.md](tests/README.md) before adding coverage; new test modules belong in the matching system-boundary directory. Repository tooling is mapped in [tools/README.md](tools/README.md).

## Design boundaries

- **Kestra** owns workflow orchestration: task order, dependencies, retries,
  fan-out, execution isolation and artifact hand-off.
- **UWflow Python** owns application validation, hard gates, bureau policy,
  affordability, pricing, final decisions and reporting.
- **AIDflow** consumes the ten normalized source scores and returns one complex
  customer-profile score plus diagnostics. It does not make lending decisions
  or calculate pricing.
- **Source adapters** must preserve the documented normalized input and
  evidence contract. Missing, stale, invalid or unavailable data must not be
  silently imputed as success.
- **The report renderer** is presentation-only and cannot recalculate scores,
  affordability, prices or decisions.
- **Runtime releases** are immutable. Do not change a checked-in release path.
  Bump `pyproject.toml`, update the version pin in the Kestra flow, build a new
  bundle with `python -m core.underwriting.tools.runtime_bundle`, and commit the new bundle.
- **Runtime source and deployment artifacts are separate.** The canonical nine-module
  source set lives in `core/python/runtime/`; the Core release builder copies those modules into the
  flat immutable Namespace Files layout. `uwflow_history/` is the independent
  historical-data package, and `tools/demo/` contains local synthetic demo commands.
  None of these source directories is mounted into production task containers;
  deployments use the protected release workflow.

## Python documentation and formatting

Every Python module has a module-level docstring. Public module functions, classes and their public methods also have docstrings that describe their responsibility. Private helpers may rely on clear names, type annotations and nearby comments where the implementation needs explanation. The immutable flat Core runtime remains a versioned payload: do not edit a checked-in runtime snapshot in place.

UWflow pins **Ruff 0.17.6** for linting and its Black-compatible formatter; Black itself is not a project dependency. Formatting is configured in `pyproject.toml` with a 100-character target line length, double quotes, four-space indentation and LF line endings. Run these checks before opening a pull request:

```bash
ruff format --check core modules tests tools
ruff check core modules tests tools
```

To apply formatting after editing Python source, run `ruff format core modules tests tools`, then rerun the tests and immutable runtime-bundle verifier. Do not format only one copy of the immutable Core runtime: if its canonical source changes, create and verify a new runtime release rather than modifying the existing release directory.

## Pull request expectations

1. Explain the problem and the design decision.
2. Add/update tests for changed behavior.
3. Update examples and documentation where appropriate.
4. Verify the immutable runtime bundle and YAML flow.
5. State whether a live Kestra execution was performed.
6. Do not include personal data, secrets or generated local artifacts.

By submitting a contribution to this project, you agree that:

1. Your contribution to the `core/` directory is licensed under
   Apache 2.0 and becomes part of that directory.
   Your contribution to all other directories is licensed under the
   project's [FSL-1.1-Apache-2.0](LICENSE) terms and becomes part of the Software.

2. You grant AIGENSYS a perpetual, irrevocable, worldwide,
   royalty-free license to use, modify, reproduce, and distribute
   your contribution in the Software or any other product or service
   that AIGENSYS offers.

3. To the extent your contribution would necessarily infringe any
   patents you own or control, you grant AIGENSYS a perpetual,
   irrevocable, worldwide, royalty-free license under those patents
   for the same purposes.

4. You represent and warrant that you have the right to grant the
   licenses above and that your contribution does not infringe any
   third-party intellectual property rights.


## Kestra task runtime and YAML changes

Keep task scripts focused on stage logic and start each Python script with `from bootstrap import ctx`. Shared path setup, Kestra access and environment parsing belong in `core/docker/bootstrap.py`; do not duplicate them in flow scripts. If the bootstrap or image dependencies change, update `core/docker/requirements.txt` / `core/docker/Dockerfile`, build the versioned images with `bash tools/docker/build-images.sh`, and align the production flow image reference. The Docker Runner still starts one isolated container per Python task; replacing it with Process Runner is an explicit isolation-model change requiring separate review.


Follow the [engineering conventions](docs/architecture/engineering-conventions.md) for Kestra YAML: centralize shared values and task defaults in Python flow builders, emit fully materialized YAML with no anchors or aliases, and keep task-specific behavior explicit. All generated flows must go through `tools/kestra/yaml.py` and be validated with `kestractl flows validate` against the target server.
