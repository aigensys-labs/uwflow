# Local Policy Studio API. The live UWflow repository is bind-mounted at /workspace
# so policy saves and candidate artifacts are written to the user's checkout.
FROM python:3.11.18-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    PYTHONPATH=/workspace/modules/policy-studio:/workspace:/workspace/core/python/runtime

WORKDIR /workspace

# Git preserves the real source commit in DEV candidate provenance when the
# mounted checkout contains .git metadata.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.30,<1" \
    "PyYAML>=6.0,<7"

EXPOSE 9000

CMD ["uvicorn", "studio.app:app", "--host", "0.0.0.0", "--port", "9000", "--reload", "--reload-dir", "/workspace/modules/policy-studio/studio", "--reload-dir", "/workspace/core/python/runtime", "--reload-dir", "/workspace/modules/lifecycle", "--reload-dir", "/workspace/modules/history/python", "--reload-dir", "/workspace/tools", "--reload-dir", "/workspace/var/workspaces"]
