# syntax=docker/dockerfile:1

FROM python:3.12-alpine AS builder

WORKDIR /build

COPY requirements.txt .
# --target instead of a plain `pip install` so the runtime stage gets only
# the library files, not pip/setuptools/wheel and their own metadata.
# All deps (including cryptography's cffi extension) ship musllinux wheels,
# so this needs no compiler on the alpine builder either. --no-compile skips
# writing __pycache__/.pyc into the image (PYTHONDONTWRITEBYTECODE keeps the
# runtime stage from regenerating them); that's ~12MB of import-time bytecode
# cache traded for a negligible cold-start cost on a long-lived server.
RUN pip install --no-cache-dir --no-compile --target=/deps -r requirements.txt \
 && find /deps -name '__pycache__' -exec rm -rf {} +

FROM python:3.12-alpine AS runtime

# Sonarr's own REST API version this image was built to call — see
# server.py's module docstring for how it's checked against Sonarr's
# GET /api discovery endpoint at runtime.
ARG SONARR_API_VERSION=v3
LABEL org.opencontainers.image.source="https://github.com/barrow1990/sonarr-mcp-server" \
      org.opencontainers.image.licenses="MIT" \
      io.sonarr-mcp.api-version="${SONARR_API_VERSION}"

# Runtime has no compiler/pip of its own to install arbitrary packages with —
# only the exact library files the builder stage resolved.
RUN python -m pip uninstall -y pip setuptools wheel 2>/dev/null || true

RUN addgroup -S app && adduser -S -G app -H -s /sbin/nologin app

WORKDIR /app
COPY --from=builder /deps /deps
COPY server.py .

ENV PYTHONPATH=/deps \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8931

# Liveness only (process up, HTTP serving) — not Sonarr connectivity, so a
# transient Sonarr outage doesn't get Dockhand/Docker restarting this
# container in a loop. Use GET /ready separately to check Sonarr connectivity.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "\
import os, sys, urllib.request; \
port = os.environ.get('MCP_PORT', '8931'); \
sys.exit(0 if urllib.request.urlopen(f'http://localhost:{port}/health', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["python", "server.py"]
