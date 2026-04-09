# syntax=docker/dockerfile:1.6
# Multi-stage build for the Athlete Training MCP system.
# Stage 1 installs dependencies into a venv; stage 2 copies just the venv
# and the source — keeps the final image small (~150MB).

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# System packages needed for libsql-client / aiohttp
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a venv to keep deps isolated and copyable
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first (cached unless pyproject.toml changes)
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --upgrade pip && pip install .


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# certifi CA bundle is needed for libsql_client → aiohttp HTTPS to Turso
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the venv from the builder stage
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY src/ ./src/
COPY scripts/ ./scripts/

# Render injects PORT; default to 8000 for local docker run
ENV PORT=8000 \
    HOST=0.0.0.0 \
    LOG_LEVEL=INFO

EXPOSE 8000

# Healthcheck so Render / docker can detect the app is up
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:'+__import__('os').environ.get('PORT','8000')+'/health',timeout=3); sys.exit(0)" || exit 1

CMD ["python", "scripts/run_api.py"]
