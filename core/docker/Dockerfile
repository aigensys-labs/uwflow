FROM python:3.11.18-slim-trixie

ARG UWFLOW_VERSION=0.0.0
ARG UWFLOW_LICENSE=Apache-2.0

LABEL org.opencontainers.image.title="UWflow Core Python Task Runtime" \
      org.opencontainers.image.description="Reusable Python execution base for application modules hosted by Kestra" \
      org.opencontainers.image.version="${UWFLOW_VERSION}" \
      org.opencontainers.image.licenses="${UWFLOW_LICENSE}" \
      org.opencontainers.image.vendor="UWflow"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY core/docker/requirements.txt /tmp/uwflow-requirements.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/uwflow-requirements.txt \
    && rm /tmp/uwflow-requirements.txt

# Kestra adapter only. Business modules remain in immutable Namespace Files.
COPY core/docker/bootstrap.py /app/bootstrap.py

CMD ["python", "--version"]
