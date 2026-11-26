# Task image builds

`build-images.sh` is the repository's Docker image build entry point. Run it from any
working directory; it resolves the repository root itself.

- Core image: `ai/uwflow-core-runtime:<project-version>`
- Optional platform dependency image: `ai/uwflow-runtime:<project-version>`

Use `--core-only` when building only the standalone Core runtime. Existing local tags
are reused unless `--replace-existing` is supplied. `--push` pushes the selected tags;
production release assembly still requires the registry's immutable `repo@sha256:...`
reference, not a mutable version tag.
