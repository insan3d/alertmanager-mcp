"""Provide typed Alertmanager API access and shared MCP runtime dependencies."""

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from prometheus_client import Counter, Histogram, start_http_server
from starlette.requests import Request

from alertmanager_mcp.config import (
    ALERTMANAGER_API_URL,
    ALERTMANAGER_TIMEOUT_SECONDS,
    METRICS_HOST,
    METRICS_PORT,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from threading import Thread
    from wsgiref.simple_server import WSGIServer

    from alertmanager_mcp.models import JsonObject, Matcher

# Export low-cardinality service metrics for operational visibility.
MCP_TOOL_REQUESTS = Counter(
    "mcp_alertmanager_tool_requests_total",
    "Total number of MCP tool executions",
    ["tool_name", "status"],
)
MCP_SILENCES_CREATED = Counter(
    "mcp_alertmanager_silences_created_total",
    "Total number of silences created via MCP",
)
ALERTMANAGER_API_LATENCY = Histogram(
    "mcp_alertmanager_api_latency_seconds",
    "Latency of Alertmanager API requests",
    ["method", "endpoint"],
)


class AlertmanagerClient:
    """Expose the Alertmanager API operations used by MCP tools."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        """Store the shared HTTP client."""

        self._http_client: httpx.AsyncClient = http_client

    async def get_status_summary(self) -> str:
        """Return a safe Alertmanager status summary."""

        status = await self._request_object("GET", "status", "status")
        version_info = status.get("versionInfo")
        cluster = status.get("cluster")
        version = version_info.get("version") if isinstance(version_info, dict) else None
        cluster_status = cluster.get("status") if isinstance(cluster, dict) else None

        return "\n".join(
            (
                f"Alertmanager version: {version or 'unknown'}",
                f"Cluster status: {cluster_status or 'unknown'}",
                f"Uptime: {status.get('uptime', 'unknown')}",
            ),
        )

    async def get_alerts(self, filters: list[str] | None) -> list[JsonObject]:
        """Return alerts matching optional Alertmanager label filters."""

        return await self._request_objects("GET", "alerts", "alerts", params=_filter_params(filters))

    async def create_silence(
        self,
        matchers: list[Matcher],
        starts_at: str,
        ends_at: str,
        created_by: str,
        comment: str,
    ) -> JsonObject:
        """Create and return an Alertmanager silence."""

        payload = _silence_payload(matchers, starts_at, ends_at, created_by, comment)
        return await self._request_object("POST", "silences", "silences", json=payload)

    async def get_silence(self, silence_id: str) -> JsonObject:
        """Return an Alertmanager silence by ID."""

        return await self._request_object("GET", f"silence/{silence_id}", "silence/{silence_id}")

    async def get_silences(self, filters: list[str] | None) -> list[JsonObject]:
        """Return silences matching optional Alertmanager label filters."""

        return await self._request_objects("GET", "silences", "silences", params=_filter_params(filters))

    async def update_silence(
        self,
        silence_id: str,
        matchers: list[Matcher],
        starts_at: str,
        ends_at: str,
        created_by: str,
        comment: str,
    ) -> JsonObject:
        """Update and return an Alertmanager silence."""

        payload = _silence_payload(matchers, starts_at, ends_at, created_by, comment)
        payload["id"] = silence_id
        return await self._request_object("POST", "silences", "silences", json=payload)

    async def expire_silence(self, silence_id: str) -> None:
        """Expire an Alertmanager silence by ID."""

        response = await self._request("DELETE", f"silence/{silence_id}", "silence/{silence_id}")
        await response.aclose()

    async def _request_object(
        self,
        method: str,
        endpoint: str,
        metric_endpoint: str,
        *,
        params: dict[str, list[str]] | None = None,
        json: JsonObject | None = None,
    ) -> JsonObject:
        """Return a decoded JSON object from Alertmanager."""

        response = await self._request(method, endpoint, metric_endpoint, params=params, json=json)
        return cast("JsonObject", _decode_json(response))

    async def _request_objects(
        self,
        method: str,
        endpoint: str,
        metric_endpoint: str,
        *,
        params: dict[str, list[str]] | None = None,
    ) -> list[JsonObject]:
        """Return decoded JSON objects from Alertmanager."""

        response = await self._request(method, endpoint, metric_endpoint, params=params)
        return cast("list[JsonObject]", _decode_json(response))

    async def _request(
        self,
        method: str,
        endpoint: str,
        metric_endpoint: str,
        *,
        params: dict[str, list[str]] | None = None,
        json: JsonObject | None = None,
    ) -> httpx.Response:
        """Send an Alertmanager request and record its latency."""

        start_time = time.monotonic()
        try:
            response = await self._http_client.request(method, endpoint, params=params, json=json)
            return response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            msg = f"Alertmanager returned HTTP {exc.response.status_code}"
            raise AlertmanagerError(msg) from exc

        except httpx.RequestError as exc:
            msg = "Alertmanager request failed"
            raise AlertmanagerError(msg) from exc

        finally:
            duration = time.monotonic() - start_time
            ALERTMANAGER_API_LATENCY.labels(method=method, endpoint=metric_endpoint).observe(duration)


class AlertmanagerError(RuntimeError):
    """Report a safe Alertmanager upstream error to MCP clients."""


@dataclass
class AppContext:
    """Store dependencies shared across MCP requests."""

    alertmanager: AlertmanagerClient


class AppMcpContext(Context[ServerSession, AppContext, Request]):
    """Provide typed access to dependencies injected into MCP requests."""


@asynccontextmanager
async def app_lifespan(_server: FastMCP[AppContext]) -> AsyncGenerator[AppContext]:
    """Start and stop dependencies shared across MCP requests."""

    metrics_server, metrics_thread = start_http_server(METRICS_PORT, addr=METRICS_HOST)
    try:
        async with httpx.AsyncClient(
            base_url=f"{ALERTMANAGER_API_URL}/",
            timeout=ALERTMANAGER_TIMEOUT_SECONDS,
        ) as http_client:
            yield AppContext(alertmanager=AlertmanagerClient(http_client))

    finally:
        _stop_metrics_server(metrics_server, metrics_thread)


@asynccontextmanager
async def track_tool(tool_name: str) -> AsyncGenerator[None]:
    """Record whether an MCP tool execution succeeded."""

    try:
        yield

    except Exception:
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        raise

    else:
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()


def get_alertmanager(ctx: AppMcpContext) -> AlertmanagerClient:
    """Return the Alertmanager client from the MCP request context."""

    return ctx.request_context.lifespan_context.alertmanager


def _filter_params(filters: list[str] | None) -> dict[str, list[str]] | None:
    """Return Alertmanager query parameters for optional label filters."""

    return {"filter": filters} if filters else None


def _decode_json(response: httpx.Response) -> object:
    """Decode an Alertmanager JSON response or raise a safe upstream error."""

    try:
        return response.json()

    except ValueError as exc:
        msg = "Alertmanager returned invalid JSON"
        raise AlertmanagerError(msg) from exc


def _silence_payload(
    matchers: list[Matcher],
    starts_at: str,
    ends_at: str,
    created_by: str,
    comment: str,
) -> JsonObject:
    """Return an Alertmanager silence payload."""

    return {
        "matchers": [_matcher_payload(matcher) for matcher in matchers],
        "startsAt": starts_at,
        "endsAt": ends_at,
        "createdBy": created_by,
        "comment": comment,
    }


def _matcher_payload(matcher: Matcher) -> JsonObject:
    """Return a JSON-compatible Alertmanager matcher."""

    payload: JsonObject = {
        "name": matcher["name"],
        "value": matcher["value"],
        "isRegex": matcher["is_regex"],
    }
    if "is_equal" in matcher:
        payload["isEqual"] = matcher["is_equal"]

    return payload


def _stop_metrics_server(server: WSGIServer, thread: Thread) -> None:
    """Stop the Prometheus metrics server."""

    server.shutdown()
    server.server_close()
    thread.join()
