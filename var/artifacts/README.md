# Generated lifecycle artifacts

This directory is created and populated by the v2 Modules as the operator workflow runs. It is intentionally empty in a clean source package; do not check local candidate, replay, bundle or evaluation outputs into the distributable package.

| Generated object | Location | Owner |
|---|---|---|
| Immutable DEV candidate | `candidates/<candidate-id>/` | Lifecycle |
| History task bundle | `tool-bundles/history/<bundle-id>/` | History |
| Generated replay flow | `replay-flows/<flow-id>.yaml` | Evaluation |
| Generated baseline flow | `baselines/<flow-id>.yaml` | Lifecycle |
| Registered replay evidence | `evaluations/<evaluation-id>/` | Evaluation |

See [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md) for the complete lifecycle, content/identity rules and immutability boundaries.
