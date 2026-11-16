## Summary

Describe the change and why it is needed.

## Changes

- 

## Validation

- [ ] `python -m pytest -q`
- [ ] `ruff check scripts tests`
- [ ] `python -m compileall -q scripts tests`
- [ ] Kestra YAML parsed successfully
- [ ] Live Kestra execution tested (describe version and result), or explicitly not tested

## Architecture and safety

- [ ] UWflow remains responsible for orchestration, underwriting policy, affordability, pricing, and final decisions.
- [ ] AIDflow remains a dedicated scoring/inference component only.
- [ ] Report rendering remains presentation-only.
- [ ] No real applicant data, credentials, access tokens, or secrets are included.
- [ ] README, examples, and CHANGELOG are updated where relevant.
