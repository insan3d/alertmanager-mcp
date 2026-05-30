"""Provide Alertmanager API access and shared MCP runtime dependencies."""

import time
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import TypeGuard, cast

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from prometheus_client import Counter, Histogram
from starlette.requests import Request

from alertmanager_mcp.config import ALERTMANAGER_API_URL, ALERTMANAGER_TIMEOUT_SECONDS
from alertmanager_mcp.models import ErrorResponse, JsonObject, JsonValue, Matcher

# Define Prometheus metrics for MCP operations and Alertmanager API latency.
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


# Keep one HTTP client alive for connection reuse across MCP requests.
@dataclass
class AppContext:
    """Store dependencies shared across MCP requests."""

    http_client: httpx.AsyncClient


class AppMcpContext(Context[ServerSession, AppContext, Request]):
    """Provide typed access to dependencies injected into MCP requests."""


@asynccontextmanager
async def app_lifespan(_server: FastMCP[AppContext]) -> AsyncGenerator[AppContext]:
    """Create and close dependencies shared across MCP requests."""

    async with httpx.AsyncClient(timeout=ALERTMANAGER_TIMEOUT_SECONDS) as http_client:
        yield AppContext(http_client=http_client)


async def make_request(
    http_client: httpx.AsyncClient,
    method: str,
    endpoint: str,
    metric_endpoint: str,
    *,
    params: Mapping[str, str] | None = None,
    json: JsonObject | None = None,
) -> httpx.Response | ErrorResponse:
    """Send an HTTP request to Alertmanager."""

    url = f"{ALERTMANAGER_API_URL}/{endpoint}"
    start_time = time.time()
    try:
        return await http_client.request(method, url, params=params, json=json)

    except httpx.RequestError as exc:
        return {"error": f"Alertmanager request failed: {exc}", "code": None}

    finally:
        duration = time.time() - start_time
        ALERTMANAGER_API_LATENCY.labels(method=method, endpoint=metric_endpoint).observe(duration)


# Normalize successful and failed responses before business logic consumes them.
def is_success(response: httpx.Response | ErrorResponse) -> TypeGuard[httpx.Response]:
    """Return whether an Alertmanager request succeeded."""

    return isinstance(response, httpx.Response) and response.status_code == HTTPStatus.OK


def get_error(response: httpx.Response | ErrorResponse) -> ErrorResponse:
    """Return a structured error for an unsuccessful Alertmanager request."""

    if isinstance(response, dict):
        return response

    return {"error": response.text, "code": response.status_code}


def get_http_client(ctx: AppMcpContext) -> httpx.AsyncClient:
    """Return the shared HTTP client from the MCP request context."""

    return ctx.request_context.lifespan_context.http_client


# Decode Alertmanager responses at the runtime boundary to keep tools strictly typed.
def get_json_object(response: httpx.Response) -> JsonObject:
    """Return a decoded JSON object from an Alertmanager response."""

    return cast("JsonObject", response.json())


def get_json_objects(response: httpx.Response) -> list[JsonObject]:
    """Return decoded JSON objects from an Alertmanager response."""

    return cast("list[JsonObject]", response.json())


def as_json_error(error: ErrorResponse) -> JsonObject:
    """Return a structured API error as a JSON-compatible object."""

    return {"error": error["error"], "code": error["code"]}


def as_json_matchers(matchers: list[Matcher]) -> list[JsonValue]:
    """Return matchers as JSON-compatible objects."""

    return [cast("JsonObject", matcher) for matcher in matchers]
