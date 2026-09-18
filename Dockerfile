FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8931

# Liveness only (process up, HTTP serving) — not Sonarr connectivity, so a
# transient Sonarr outage doesn't get Dockhand/Docker restarting this
# container in a loop. Use GET /ready separately to check Sonarr connectivity.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "\
import os, sys, urllib.request; \
port = os.environ.get('MCP_PORT', '8931'); \
sys.exit(0 if urllib.request.urlopen(f'http://localhost:{port}/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["python", "server.py"]
