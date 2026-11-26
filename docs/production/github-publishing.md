# Publishing this repository on GitHub

This project is delivered as a complete repository template. The archive is not connected to a remote GitHub repository and does not publish itself. This guide covers initial repository setup and the governance controls required by the current approved-release deployment workflow.

## 1. Before the first push

1. Review the Apache-2.0 license and add any required copyright notices for your own original contributions.
2. Review the synthetic-data disclaimer and repository visibility with the intended owner.
3. Create an empty GitHub repository. Do not initialize it with an additional README, license or `.gitignore`.
4. Extract the archive and run the guided initializer from the repository root:

   ```bash
   bash tools/guides/workflow/23-initialize-github-repository.sh
   ```

   The initializer stages the repository, shows a summary and asks before committing and pushing. It refuses to stage ignored local secrets and analyst workspaces.

**Production-provenance note:** candidate builds from a ZIP extraction without Git metadata are marked `unverified` and cannot be promoted. For governed DEV and production work, use a real Git checkout. After the initial push, clone the repository into a clean working directory and build candidates from that checkout.

## 2. Protect the default branch

Create a branch ruleset for `main`:

- Require pull requests before merging.
- Require the CI checks to pass for the supported Python versions.
- Require at least one independent review for changes to Core runtime source, policy compiler, Kestra flows, candidate/release tooling and deployment workflows.
- Block force pushes and branch deletion.
- Restrict bypass permissions to designated repository administrators.

Configure the exact status-check names after the first CI run appears in GitHub.

## 3. Configure the production Environment

Create a GitHub Environment named `uwflow-production`:

- Require one or more designated reviewers for deployments.
- Restrict deployment branches to protected `main`.
- Add `KESTRA_HOSTNAME`, `KESTRA_USERNAME` and `KESTRA_PASSWORD` as environment secrets.
- Use a dedicated Kestra service account with only the permissions required to upload Namespace Files and create/update the UWflow flow in `com.ai.credit.production`.
- Configure the production Kestra secret `UNDERWRITING_WEBHOOK_KEY` separately through the approved Kestra secret store; it is not a GitHub deployment secret.

For private Kestra endpoints, use a self-hosted runner inside the approved network. Do not expose a production Kestra API publicly just to make GitHub-hosted runners reach it.

## 4. Prepare an approved release for deployment

The current deployment workflow is intentionally manual and release-ID based; it is not triggered by a semantic-version tag. Its GitHub Actions trigger is `workflow_dispatch`, and the only deploy input is the exact approved `release_id`. The process is:

1. Create a strategy workspace from Core defaults or fork an existing DEV candidate or approved release.
2. Build an immutable DEV candidate from the selected workspace and pinned Core runtime.
3. Publish and evaluate the candidate in Kestra DEV against frozen historical evidence.
4. Register the evaluation evidence and obtain the institution's explicit underwriting/risk approval. The approval JSON is an attestation record; it is not itself an authenticated signature or RBAC system.
5. Assemble an immutable package under `var/releases/approved/<release-id>/`, supplying the release ID explicitly and pinning the Core task image by OCI digest.
6. Include the approved release directory and the required approval/provenance references in a reviewed pull request. Merge to protected `main`.
7. In GitHub Actions, manually dispatch **Deploy approved UWflow release to Kestra PROD** from `main`, enter the exact `release_id`, and complete the `uwflow-production` Environment review.

The workflow verifies the package's candidate/evaluation/approval references, manifests, checksums, production flow and digest-pinned Core image. It uploads only the package's Core runtime to `runtime/releases/<release-id>/`, validates the approved flow and deploys it to `com.ai.credit.production`. Platform Modules are not deployed into the PROD underwriting execution path.

## 5. Repository and security settings

- Enable Dependabot security/version updates and secret scanning/push protection where available.
- Allow only required GitHub Actions; action references in workflows are pinned to full commit SHAs.
- Keep default workflow permissions read-only. Do not grant broad write permissions to CI jobs.
- Keep pull-request CI, business approval and production Environment approval as separate controls.
- Semantic-version tags may be used for source/package release management, but they do not trigger production deployment.

## 6. Deployment record and rollback

After deployment, the workflow uploads its provenance directory as a GitHub Actions artifact and writes `var/deployments/production/current.json` in the workflow checkout. The local analyst checkout is not automatically synchronized; set `UWFLOW_CURRENT_PROD_RELEASE` in `.env` or synchronize the pointer when the currently deployed release should be highlighted in Policy Studio.

A rollback is a new manual deployment of a previously approved immutable release ID, not an edit to the current release.

See [Governed release boundary](production-release-workflow.md) for assembly and approval details and [Deployment](deployment.md) for live Kestra verification.
