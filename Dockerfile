FROM ghcr.io/astral-sh/uv:python3.14-alpine

WORKDIR /app

# Install locked runtime dependencies before copying the application for better layer caching.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Run the service as an unprivileged user.
COPY alertmanager_mcp ./alertmanager_mcp
RUN addgroup -S app && adduser -S app -G app
USER app

# Containers must listen beyond localhost for published ports to be reachable.
ENV PATH="/app/.venv/bin:$PATH" \
    MCP_HOST=0.0.0.0 \
    METRICS_HOST=0.0.0.0

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=8s --retries=3 \
    CMD ["python", "-m", "alertmanager_mcp.healthcheck"]

CMD ["python", "-m", "alertmanager_mcp"]
