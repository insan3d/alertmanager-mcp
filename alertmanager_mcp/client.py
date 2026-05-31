"""Provide typed Alertmanager API access and shared MCP runtime dependencies."""

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import httpx
from prometheus_client import Counter, Histogram, start_http_server

from alertmanager_mcp.config import SETTINGS

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from alertmanager_mcp.models import (
        JsonObject,
        JsonValue,
        Matcher,
        NonEmptyFilters,
        NonEmptyMatchers,
        Rfc3339Timestamp,
        SilenceId,
    )

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

        self._http_client = http_client

    async def get_status_summary(self) -> str:
        """Return a safe Alertmanager status summary."""

        status = cast("JsonObject", await self._request_json("GET", "status", "status"))
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

    async def get_alerts(self, filters: NonEmptyFilters) -> list[JsonObject]:
        """Return alerts matching Alertmanager label filters."""

        return cast("list[JsonObject]", await self._request_json("GET", "alerts", "alerts", params={"filter": filters}))

    async def create_silence(
        self,
        matchers: NonEmptyMatchers,
        starts_at: Rfc3339Timestamp,
        ends_at: Rfc3339Timestamp,
        created_by: str,
        comment: str,
    ) -> JsonObject:
        """Create and return an Alertmanager silence."""

        payload = _silence_payload(matchers, starts_at, ends_at, created_by, comment)
        return cast("JsonObject", await self._request_json("POST", "silences", "silences", json=payload))

    async def get_silence(self, silence_id: SilenceId) -> JsonObject:
        """Return an Alertmanager silence by ID."""

        return cast(
            "JsonObject",
            await self._request_json("GET", f"silence/{silence_id}", "silence/{silence_id}"),
        )

    async def get_silences(self, filters: NonEmptyFilters) -> list[JsonObject]:
        """Return silences matching Alertmanager label filters."""

        return cast(
            "list[JsonObject]",
            await self._request_json("GET", "silences", "silences", params={"filter": filters}),
        )

    async def update_silence(
        self,
        silence_id: SilenceId,
        matchers: NonEmptyMatchers,
        starts_at: Rfc3339Timestamp,
        ends_at: Rfc3339Timestamp,
        created_by: str,
        comment: str,
    ) -> JsonObject:
        """Update and return an Alertmanager silence."""

        payload = _silence_payload(matchers, starts_at, ends_at, created_by, comment)
        payload["id"] = str(silence_id)
        return cast("JsonObject", await self._request_json("POST", "silences", "silences", json=payload))

    async def expire_silence(self, silence_id: SilenceId) -> None:
        """Expire an Alertmanager silence by ID."""

        response = await self._request("DELETE", f"silence/{silence_id}", "silence/{silence_id}")
        await response.aclose()

    async def _request_json(
        self,
        method: str,
        endpoint: str,
        metric_endpoint: str,
        *,
        params: dict[str, list[str]] | None = None,
        json: JsonObject | None = None,
    ) -> JsonValue:
        """Return a decoded JSON response from Alertmanager."""

        response = await self._request(method, endpoint, metric_endpoint, params=params, json=json)
        try:
            return cast("JsonValue", response.json())

        except ValueError as exc:
            msg = "Alertmanager returned invalid JSON"
            raise AlertmanagerError(msg) from exc

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


_alertmanager_client: AlertmanagerClient | None = None


@asynccontextmanager
async def app_lifespan() -> AsyncGenerator[None]:
    """Start and stop dependencies shared across MCP requests."""

    global _alertmanager_client  # noqa: PLW0603  # The ASGI lifespan owns this process-scoped dependency.

    metrics_server, metrics_thread = start_http_server(SETTINGS.metrics_port, addr=SETTINGS.metrics_host)
    try:
        async with httpx.AsyncClient(
            base_url=f"{SETTINGS.alertmanager_api_url}/",
            timeout=httpx.Timeout(
                connect=SETTINGS.alertmanager_connect_timeout_seconds,
                read=SETTINGS.alertmanager_read_timeout_seconds,
                write=SETTINGS.alertmanager_write_timeout_seconds,
                pool=SETTINGS.alertmanager_pool_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=SETTINGS.alertmanager_max_connections,
                max_keepalive_connections=SETTINGS.alertmanager_max_keepalive_connections,
                keepalive_expiry=SETTINGS.alertmanager_keepalive_expiry_seconds,
            ),
        ) as http_client:
            _alertmanager_client = AlertmanagerClient(http_client)
            try:
                yield

            finally:
                _alertmanager_client = None

    finally:
        metrics_server.shutdown()
        metrics_server.server_close()
        metrics_thread.join()


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


def get_alertmanager() -> AlertmanagerClient:
    """Return the process-scoped Alertmanager client."""

    if _alertmanager_client is None:
        msg = "Alertmanager client is unavailable outside the application lifespan"
        raise RuntimeError(msg)

    return _alertmanager_client


def _silence_payload(
    matchers: NonEmptyMatchers,
    starts_at: Rfc3339Timestamp,
    ends_at: Rfc3339Timestamp,
    created_by: str,
    comment: str,
) -> JsonObject:
    """Return an Alertmanager silence payload."""

    return {
        "matchers": [_matcher_payload(matcher) for matcher in matchers],
        "startsAt": starts_at.isoformat(),
        "endsAt": ends_at.isoformat(),
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
