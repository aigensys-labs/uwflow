# The repository frontend is mounted read-only at /workspace/frontend.
# npm dependencies and the Vite optimizer cache live in a separate named
# volume at /workspace/node_modules, outside that bind mount.
FROM node:26-bookworm-slim

ENV npm_config_audit=false \
    npm_config_fund=false \
    npm_config_update_notifier=false

WORKDIR /workspace

# Keep a package manifest at the dependency root. The entrypoint synchronizes
# it from the mounted frontend/package.json before checking/installing deps.
COPY modules/policy-studio/frontend/package.json ./package.json
RUN npm install --no-package-lock --no-audit --no-fund

COPY modules/policy-studio/frontend/ ./frontend/
COPY modules/policy-studio/docker/studio/frontend-entrypoint.sh /usr/local/bin/uwflow-studio-frontend
RUN chmod 0755 /usr/local/bin/uwflow-studio-frontend \
    && printf '%s %s\n' "$(sha256sum frontend/package.json | awk '{print $1}')" "$(node --version)" > node_modules/.uwflow-package-hash \
    && chown -R node:node /workspace /usr/local/bin/uwflow-studio-frontend

USER node
EXPOSE 5173
ENTRYPOINT ["/usr/local/bin/uwflow-studio-frontend"]
