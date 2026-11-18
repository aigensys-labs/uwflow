FROM python:3.11.18-slim-trixie

# Install non-interactive runtime dependencies once
RUN pip install --no-cache-dir \
    kestra==2.0.0 \
    reportlab==5.1.0

WORKDIR /app
