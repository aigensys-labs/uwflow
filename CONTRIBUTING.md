# Contributing

Thank you for considering a contribution to UWflow. This repository is a
synthetic demonstration; contributions must preserve the demo-only boundary and
must not introduce real applicant information, credentials or production data.

## Development setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Checks before submitting

```bash
python -m pytest -q
ruff check scripts tests tools
python -m compileall -q scripts tests tools
python tools/build_runtime_bundle.py --check
```

Generated reports and local `.env` files are ignored by Git. Never attach real
credit reports, identity documents, bank statements, credentials or production
payloads to issues or pull requests.

## Design boundaries

- **UWflow** owns orchestration, application validation, hard gates, bureau
  policy, affordability, pricing, final decisions and reporting.
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
  bundle with `python tools/build_runtime_bundle.py`, and commit the new bundle.
- **Production code belongs in Kestra Namespace Files.** The `scripts/` folder
  is the Git source tree; it is never mounted from the host into production.
  Deployments must use the protected release workflow.

## Pull request expectations

1. Explain the problem and the design decision.
2. Add/update tests for changed behavior.
3. Update examples and documentation where appropriate.
4. Verify the immutable runtime bundle and YAML flow.
5. State whether a live Kestra execution was performed.
6. Do not include personal data, secrets or generated local artifacts.

By submitting a contribution, you agree that it may be redistributed under
the repository's [Apache 2.0 License](LICENSE).
