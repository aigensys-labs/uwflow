# Architecture and component boundaries

## Context

UWflow is the underwriting application. Kestra orchestrates execution but does not own the credit policy. AIDflow is an inference component called by UWflow; it returns one customer-profile score and cannot approve or decline an application.

## Runtime path

The source code under `scripts/` is maintained in GitHub. `tools/build_runtime_bundle.py` creates a deterministic, versioned release under `kestra/namespace-files/runtime/releases/<version>/`. CI uploads this directory to the matching Kestra Namespace Files path. The flow's `namespaceFiles.include` is pinned to that version and every script task adds that version root to `sys.path` using the runner-provided `WORKING_DIR`.

No application code is mounted from the Kestra host filesystem. Each Python stage runs in an isolated Docker task container; Kestra injects only the explicit versioned Namespace Files release into that task working directory. The Kestra worker itself does not need the application source tree or a host Python installation.

## Responsibilities

| Layer | Owns | Must not own |
|---|---|---|
| GitHub | Approved source, PR approvals, test evidence, release tags | Runtime execution |
| Kestra | Ordering, retries, fan-out, execution metadata, outputs and artifacts | Credit policy/model implementation |
| UWflow adapters | Provider contract normalization and provenance | AIDflow inference or final risk modelling |
| AIDflow | Ten-input profile inference, model diagnostics and lineage | Bureau policy, affordability, price, loan offer or final decision |
| UWflow decision engine | Hard gates, bureau precedence, affordability, risk tier, pricing and final outcome | Provider-specific transport |
| UWflow reporting | Human-readable presentation of an immutable decision object | Decision recalculation |

## Release immutability

A release directory is content-addressed by its manifest and named by semantic version. Never overwrite an existing release with different content. Changes create a new version and path. The flow change and new bundle are committed together so a review shows exactly which source release the flow will execute.

## Execution flow

1. Stage 1 verifies the loaded runtime manifest and evaluates hard gates.
2. Stage 2 obtains a synthetic bureau record and applies the demonstration bureau band.
3. Stage 3 applies consent and eligibility rules to source collection.
4. Stage 4 fans out to ten source adapters; a no-op sentinel preserves output shape when no real source call is permitted.
5. Stage 5 sends the ten normalized scores to AIDflow and receives one customer-profile score.
6. Stage 6 applies UWflow policy and calculates affordability, terms and final decision.
7. Stage 7 renders HTML, PDF and JSON from the finalized decision, without recalculating it.


For the local demonstration, the Python image is referenced by the patch-level tag `python:3.11.18-slim-trixie` to keep the setup simple and avoid a platform-specific digest mismatch. A production deployment should select, verify and pin the appropriate OCI digest for its target architecture.
