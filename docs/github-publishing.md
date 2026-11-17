# Publishing this repository on GitHub

This project is delivered as a complete repository template. The archive is not connected to a remote GitHub repository and does not publish itself.

## 1. Before the first push

1. Replace the `[COPYRIGHT HOLDER]` placeholder in `LICENSE` with the actual individual or legal entity that owns the rights to this code. Do not guess or leave the placeholder in a public release.
2. Review `README.md`, the synthetic-data disclaimer, and the Apache 2.0 licensing decision with the intended repository owner.
3. Choose the repository visibility and create an empty GitHub repository. Do not initialize it with an additional README, license, or `.gitignore`, because those files are already present.
4. Extract the archive and initialize/push the repository:

   ```bash
   git init -b main
   git add .
   git commit -m "Initial UWflow governed Kestra underwriting demo"
   git remote add origin <YOUR_GITHUB_REPOSITORY_URL>
   git push -u origin main
   ```

## 2. Protect the default branch

Create a branch ruleset for `main`:

- Require pull requests before merging.
- Require the CI checks to pass for Python 3.11, 3.12 and 3.13.
- Require at least one independent review for changes to runtime scripts, the Kestra flow, release bundle, or deployment workflow.
- Block force pushes and branch deletion.
- Restrict bypass permissions to designated repository administrators.

The exact status-check names may be selected after the first CI run appears in GitHub.

## 3. Protect release tags

Create a tag ruleset matching `v*` and restrict tag creation/update/deletion to release maintainers. The deployment workflow accepts only a tag equal to `v<project.version>`; for example, `pyproject.toml` version `1.2.2` requires tag `v1.2.2`.

Where your governance process supports it, sign release tags and verify signatures as part of the release approval. Never move or recreate a published release tag.

## 4. Configure the production environment

Create a GitHub Environment named `uwflow-production`:

- Require one or more designated reviewers.
- Restrict deployments to the protected `v*` release tags.
- Add the deployment secrets `KESTRA_HOSTNAME`, `KESTRA_USERNAME`, and `KESTRA_PASSWORD`.
- Use a dedicated Kestra service account with only the permissions required to upload Namespace Files and create/update the UWflow flow in `com.ai.credit.production`. In Kestra Open Source, namespaces are implicit; namespace creation is an Enterprise feature.

For private Kestra endpoints, run the deployment workflow on a self-hosted runner inside the approved network. Do not expose a production Kestra API publicly solely to make GitHub-hosted runners reach it.

## 5. Repository settings

- Enable Dependabot security and version updates.
- Enable secret scanning and push protection where available.
- Allow only the GitHub Actions required by the workflows; all action references are pinned to full commit SHAs.
- Set Actions workflow permissions to read repository contents by default. Do not grant broad write permissions to CI jobs.
- Keep production environment approval separate from pull-request CI.

## 6. First controlled release

After the first reviewed merge, create the protected tag `v1.2.2` and push it. Approve the `uwflow-production` environment deployment. The workflow validates the repository, uploads the immutable runtime bundle to Kestra Namespace Files, validates the flow against the target Kestra instance, and deploys the read-only flow.

For the local one-container demo bootstrap, follow [the deployment guide](deployment.md) instead of configuring production secrets.
