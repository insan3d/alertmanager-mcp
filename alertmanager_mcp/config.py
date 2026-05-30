"""Load Alertmanager MCP configuration from environment variables."""

import os
from typing import Final


def _get_env_int(name: str, default: int) -> int:
    """Return an integer environment variable or its default value."""

    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)

    except ValueError as exc:
        msg = f"{name} must be an integer, got {value!r}"
        raise ValueError(msg) from exc


# Alertmanager connection settings.
ALERTMANAGER_URL: Final = os.getenv("ALERTMANAGER_URL", "http://localhost:9093").rstrip("/")
ALERTMANAGER_API_PREFIX: Final = os.getenv("ALERTMANAGER_API_PREFIX", "/api/v2").strip("/")
ALERTMANAGER_TIMEOUT_SECONDS: Final = _get_env_int("ALERTMANAGER_TIMEOUT_SECONDS", 10)
ALERTMANAGER_API_URL: Final = f"{ALERTMANAGER_URL}/{ALERTMANAGER_API_PREFIX}"

# MCP Streamable HTTP listener settings.
MCP_NAME: Final = os.getenv("MCP_NAME", "Alertmanager API Proxy")
MCP_HOST: Final = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT: Final = _get_env_int("MCP_PORT", 8000)
MCP_HTTP_PATH: Final = os.getenv("MCP_HTTP_PATH", "/mcp")

# Prometheus metrics listener settings.
METRICS_HOST: Final = os.getenv("METRICS_HOST", "127.0.0.1")
METRICS_PORT: Final = _get_env_int("METRICS_PORT", 8001)
