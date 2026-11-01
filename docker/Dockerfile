# Multi-stage production OCI Dockerfile for Hexaqueue
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:d8c5ddbfd2966113b28b52e3e5730a9163e9f4560b2984951167dc8a4e32049d AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install workspace dependencies using bind mounts for maximum layer caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy entire source workspace and sync all workspace members
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ------------------------------------------------------------------------------
# Runtime Base Stage
# ------------------------------------------------------------------------------
FROM python:3.13-slim-bookworm@sha256:cf3b03f0b2f56708b76c8c1e847c21f92e59df0e21a711ef8ae55cb56041c2d9 AS runtime-base

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

# Create non-root system user
RUN groupadd -r -g 10001 appuser && \
    useradd -r -u 10001 -g appuser -d /app -s /sbin/nologin appuser

# Copy virtualenv and application from builder
COPY --from=builder --chown=appuser:appuser /app /app

USER 10001:10001

# ------------------------------------------------------------------------------
# Server Target
# ------------------------------------------------------------------------------
FROM runtime-base AS server

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

ENTRYPOINT ["hq", "server", "start", "--host", "0.0.0.0", "--port", "8000"]

# ------------------------------------------------------------------------------
# Worker Target
# ------------------------------------------------------------------------------
FROM runtime-base AS worker

ENTRYPOINT ["hq"]
CMD ["nodes", "list"]
