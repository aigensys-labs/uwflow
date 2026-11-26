# Platform Runtime

Platform Runtime provides the optional task-image dependency layer for modules that need PostgreSQL, Parquet and comparative-reporting libraries. It is built on top of `ai/uwflow-core-runtime:<version>`; it does not replace the Core image or add underwriting decision logic.

Core-only Kestra execution uses `ai/uwflow-core-runtime:<version>` and does not need this image. The platform image is used by selected History/Evaluation and reporting tasks.

## Build task images

From the repository root, build both images with:

```bash
bash tools/docker/build-images.sh
```

Build only the Core image for the standalone seven-stage demo:

```bash
bash tools/docker/build-images.sh --core-only
```

The resulting tags follow the semantic project version in `pyproject.toml`:

- `ai/uwflow-core-runtime:<version>` — Kestra/Python Core execution and Stage 7 applicant reports;
- `ai/uwflow-runtime:<version>` — optional module task dependencies layered on Core.

The underwriting application source is not copied into either image. It remains in immutable Kestra Namespace Files bundles and is selected by each flow.
