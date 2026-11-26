# Core underwriting application

This is the underwriting domain implementation that was part of the original UWflow Core. It is not an optional platform module.

It owns the Core decision stages and baseline configuration:

- baseline Stage 1 hard-gate and Stage 3 source-planning policy specifications;
- the field catalog and policy schemas used to validate those baseline policies;
- synthetic application examples and individual applicant report fixtures;
- the runtime bundle builder and verifier for the canonical Python implementation.

The executable Python source is in [../python/runtime/](../python/runtime/). The seven-stage Kestra flow is in [../kestra/dev/flows/](../kestra/dev/flows/), with immutable runtime releases in [../kestra/namespace-files/runtime/releases/](../kestra/namespace-files/runtime/releases/).

The Policy Studio module edits the canonical policy specifications here and generates the Core `policy_generated.py` source. Lifecycle builds immutable DEV candidates from the Core runtime and approved policy sources. The decision engine itself remains Core-owned.
