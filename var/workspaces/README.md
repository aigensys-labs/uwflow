# Analyst workspaces

Mutable analyst strategy work lives under `strategies/<workspace-id>/`. Each workspace contains its metadata and the policy specifications that Policy Studio is authorised to edit. A workspace can start from Core defaults or be forked from a verified DEV candidate or approved production release.

For source selection, workspace ancestry, pinned runtime identity and the transition from workspace to immutable candidate, see [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md#1-create-or-fork-a-workspace).
