# Alertmanager MCP

An HTTP MCP server that exposes a focused subset of the Prometheus Alertmanager API. It supports alert inspection and silence management, with a guided prompt for urgent incident silences.

## Features

- Stateless Streamable HTTP MCP endpoint with JSON responses.
- Alert listing and silence lifecycle tools.
- Safe Alertmanager status resource.
- Incident-oriented `emergency_silence_flow` prompt.
- Prometheus metrics on a separate listener.
- Shared HTTP client with configurable timeout and connection reuse.

## Run

Install dependencies and start the server:

```bash
uv sync
uv run python -m alertmanager_mcp
```

Python 3.14 or newer is required.

Defaults:

- MCP endpoint: `http://127.0.0.1:8000/mcp`
- Metrics endpoint: `http://127.0.0.1:8001/metrics`
- Alertmanager API: `http://localhost:9093/api/v2`

## Configuration

Configuration is read from environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALERTMANAGER_URL` | `http://localhost:9093` | Alertmanager base URL |
| `ALERTMANAGER_CONNECT_TIMEOUT_SECONDS` | `5` | Alertmanager connect timeout |
| `ALERTMANAGER_READ_TIMEOUT_SECONDS` | `10` | Alertmanager read timeout |
| `ALERTMANAGER_WRITE_TIMEOUT_SECONDS` | `10` | Alertmanager write timeout |
| `ALERTMANAGER_POOL_TIMEOUT_SECONDS` | `5` | Alertmanager connection-pool timeout |
| `ALERTMANAGER_MAX_CONNECTIONS` | `100` | Maximum Alertmanager HTTP connections |
| `ALERTMANAGER_MAX_KEEPALIVE_CONNECTIONS` | `20` | Maximum idle keep-alive connections |
| `ALERTMANAGER_KEEPALIVE_EXPIRY_SECONDS` | `5` | Idle keep-alive expiry |
| `MCP_NAME` | `Alertmanager API Proxy` | MCP server name |
| `MCP_HOST` | `127.0.0.1` | MCP listener host |
| `MCP_PORT` | `8000` | MCP listener port |
| `MCP_HTTP_PATH` | `/mcp` | Streamable HTTP path |
| `METRICS_HOST` | `127.0.0.1` | Metrics listener host |
| `METRICS_PORT` | `8001` | Metrics listener port |
| `MCP_HEALTHCHECK_URL` | Derived from `MCP_PORT` and `MCP_HTTP_PATH` | Optional MCP healthcheck override |
| `METRICS_HEALTHCHECK_URL` | Derived from `METRICS_PORT` | Optional metrics healthcheck override |
| `HEALTHCHECK_TIMEOUT_SECONDS` | `5` | E2E healthcheck timeout |

## Docker

Build and run the Alpine-based container:

```bash
docker build -t alertmanager-mcp .
docker run --rm \
  -p 8000:8000 \
  -p 8001:8001 \
  --add-host=host.docker.internal:host-gateway \
  -e ALERTMANAGER_URL=http://host.docker.internal:9093 \
  alertmanager-mcp
```

The image uses Astral's official `ghcr.io/astral-sh/uv:python3.14-alpine` base image and installs dependencies from `uv.lock`. The tag intentionally follows the latest Python 3.14 Alpine image. The container binds both listeners to `0.0.0.0`; published ports and network access should still be restricted in production.

## Docker Compose

Start the MCP server with an empty Alertmanager instance:

```bash
docker compose up --build --wait
```

The MCP container healthcheck initializes an MCP session, verifies the tool list, reads `alertmanager://status` through the empty Alertmanager instance, and checks the metrics listener. Stop the stack with:

```bash
docker compose down
```

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

`list_alerts` and `list_silences` require one or more Alertmanager label filters, for example `alertname="HighLatency"`. Multiple filters are passed to Alertmanager as repeated `filter` query parameters.

## Metrics

The service exports:

- `mcp_alertmanager_tool_requests_total`
- `mcp_alertmanager_silences_created_total`
- `mcp_alertmanager_api_latency_seconds`

Metric labels use stable route names to avoid unbounded cardinality.

## Development Checks

```bash
uv run ruff check alertmanager_mcp pyproject.toml
uv run mypy alertmanager_mcp
uv run basedpyright alertmanager_mcp
```

## Deployment Note

The MCP server does not configure authentication itself. Keep the default localhost binding or place it behind an authenticated reverse proxy before exposing it to a network.
