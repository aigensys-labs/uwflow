ARG CORE_IMAGE=ai/uwflow-core-runtime
ARG UWFLOW_VERSION=2.0.0

FROM ${CORE_IMAGE}:${UWFLOW_VERSION}

ARG UWFLOW_VERSION=2.0.0
ARG UWFLOW_LICENSE=Apache-2.0

LABEL org.opencontainers.image.title="UWflow Platform Task Runtime" \
      org.opencontainers.image.description="UWflow module dependencies layered on the reusable Core task runtime" \
      org.opencontainers.image.version="${UWFLOW_VERSION}" \
      org.opencontainers.image.licenses="${UWFLOW_LICENSE}" \
      org.opencontainers.image.vendor="UWflow"

COPY modules/platform-runtime/requirements.txt /tmp/uwflow-platform-requirements.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/uwflow-platform-requirements.txt \
    && rm /tmp/uwflow-platform-requirements.txt

CMD ["python", "--version"]
