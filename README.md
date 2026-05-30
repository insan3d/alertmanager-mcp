# Alertmanager MCP

An HTTP MCP server that exposes a focused subset of the Prometheus Alertmanager API. It supports alert inspection and silence management, with a guided prompt for urgent incident silences.

## Features

- Streamable HTTP MCP endpoint.
- Alert listing and silence lifecycle tools.
- Alertmanager configuration resource.
- Incident-oriented `emergency_silence_flow` prompt.
- Prometheus metrics on a separate listener.
- Shared HTTP client with configurable timeout and connection reuse.

## Run

Install dependencies and start the server:

```bash
uv sync
uv run python -m alertmanager_mcp
```

Defaults:

- MCP endpoint: `http://127.0.0.1:8000/mcp`
- Metrics endpoint: `http://127.0.0.1:8001/metrics`
- Alertmanager API: `http://localhost:9093/api/v2`

## Configuration

Configuration is read from environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALERTMANAGER_URL` | `http://localhost:9093` | Alertmanager base URL |
| `ALERTMANAGER_API_PREFIX` | `/api/v2` | Alertmanager API prefix |
| `ALERTMANAGER_TIMEOUT_SECONDS` | `10` | Alertmanager request timeout |
| `MCP_NAME` | `Alertmanager API Proxy` | MCP server name |
| `MCP_HOST` | `127.0.0.1` | MCP listener host |
| `MCP_PORT` | `8000` | MCP listener port |
| `MCP_HTTP_PATH` | `/mcp` | Streamable HTTP path |
| `METRICS_HOST` | `127.0.0.1` | Metrics listener host |
| `METRICS_PORT` | `8001` | Metrics listener port |

## Docker

Build and run the Alpine-based container:

```bash
docker build -t alertmanager-mcp .
docker run --rm \
  -p 8000:8000 \
  -p 8001:8001 \
  -e ALERTMANAGER_URL=http://host.docker.internal:9093 \
  alertmanager-mcp
```

The image uses Astral's official `ghcr.io/astral-sh/uv:python3.14-alpine` base image and installs dependencies from `uv.lock`. The container binds both listeners to `0.0.0.0`; published ports and network access should still be restricted in production.

## MCP Surface

Resource:

- `alertmanager://status`

Prompt:

- `emergency_silence_flow`

Tools:

- `list_alerts`
- `create_silence`
- `get_silence`
- `list_silences`
- `update_silence`
- `expire_silence`

## Metrics

The service exports:

- `mcp_alertmanager_tool_requests_total`
- `mcp_alertmanager_silences_created_total`
- `mcp_alertmanager_api_latency_seconds`

Metric labels use stable route names to avoid unbounded cardinality.

## Development Checks

```bash
.venv/bin/ruff check alertmanager_mcp pyproject.toml
.venv/bin/mypy alertmanager_mcp
.venv/bin/basedpyright alertmanager_mcp
```

## Deployment Note

The MCP server does not configure authentication itself. Keep the default localhost binding or place it behind an authenticated reverse proxy before exposing it to a network.
