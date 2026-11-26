## Summary

Describe the change and why it is needed.

## Changes

- 

## Validation

- [ ] `python -m pytest -q`
- [ ] `ruff check scripts studio tests tools`
- [ ] `python -m compileall -q scripts studio tests tools`
- [ ] `python -m tools.policy.compiler --check`
- [ ] `python -m core.underwriting.tools.runtime_bundle --check`
- [ ] `python -m modules.history.tools.history_tools_bundle --check`
- [ ] Kestra YAML and Docker Compose definitions parsed successfully
- [ ] Live Kestra validation/execution tested, or explicitly marked as not performed

## Architecture and safety

- [ ] Kestra remains responsible for orchestration; UWflow Python owns underwriting calculations and decisions.
- [ ] AIDflow remains an inference/scoring component and does not approve, decline or price applications.
- [ ] Policy definitions remain typed, allow-listed and compiler-validated.
- [ ] Champion, candidate, dataset and runtime artifacts remain immutable and separately identified.
- [ ] Production promotion uses reviewed Git changes and the protected release workflow.
- [ ] No real applicant data, credentials, access tokens or secrets are included.
- [ ] README, the relevant documentation group and CHANGELOG are updated where appropriate.
