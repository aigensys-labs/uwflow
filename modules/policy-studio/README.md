# Policy Studio

Policy Studio is the analyst interface for creating and editing independent strategy workspaces. It reads Core's field catalogue and default strategy, then saves editable policy specifications and generated preview code only under `var/workspaces/strategies/<workspace-id>/`. Analysts can start from Core defaults or fork a verified DEV candidate or approved release; a fork records exact ancestry and does not modify its source.

The current editor supports Stage 1 and Stage 3. Other stages remain protected or planned as shown in the Studio. The default Core-based workspace is created when the Studio first requests workspace state; importing or starting the API does not write analyst data. Saving a workspace does not modify Core, build a candidate, publish Kestra flows, run historical replay or deploy production.


For the complete object lifecycle, storage locations, identity model and immutability rules, see the [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md).

## Use Policy Studio

| Guide | Use it to… |
|---|---|
| [Policy Studio — local authoring](../../docs/studio/policy-studio.md) | Start the editor, create/select/fork a workspace, edit supported Stage 1/Stage 3 policies, validate, preview and save. |
| [DEV candidate lifecycle](../../docs/studio/policy-studio-dev.md) | Select the exact baseline, build an immutable candidate, publish it to DEV and prepare paired replay. |
| [Policy specifications and compiler](../../docs/studio/policy-studio-compiler.md) | Understand supported schemas, fields, operators, validation and generated Python. |
| [End-to-end DEV workflow](../../docs/development/end-to-end-dev-workflow.md) | Follow the entire platform journey from environment setup through replay and a controlled policy change. |

**Boundary:** Studio authors and validates strategy. Lifecycle snapshots it. Evaluation runs replay. Production handles approval and deployment. Studio itself does not execute underwriting or deploy production.
