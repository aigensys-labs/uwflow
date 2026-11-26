# Production deployment records

The production deployment workflow maintains `production/current.json` as the current deployed-release pointer and appends successful deployment provenance under `production/history/`. These records are written only after the approved runtime and production flow have been deployed successfully.

See [UWflow lifecycle and storage model](../../docs/architecture/lifecycle-and-storage.md#6-deploy-and-roll-back) for deployment identity, synchronization and rollback semantics.
