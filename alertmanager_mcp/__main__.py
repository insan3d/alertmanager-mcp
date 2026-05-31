#!/usr/bin/env python3

"""Expose Alertmanager operations through an HTTP MCP server."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

from alertmanager_mcp.client import (
    MCP_SILENCES_CREATED,
    app_lifespan,
    get_alertmanager,
    track_tool,
)
from alertmanager_mcp.config import SETTINGS
from alertmanager_mcp.models import (  # noqa: TC001  # FastMCP resolves tool annotations at runtime.
    JsonObject,
    NonEmptyFilters,
    NonEmptyMatchers,
    Rfc3339Timestamp,
    SilenceId,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Configure the MCP server's Streamable HTTP listener.
mcp = FastMCP(
    SETTINGS.mcp_name,
    host=SETTINGS.mcp_host,
    port=SETTINGS.mcp_port,
    streamable_http_path=SETTINGS.mcp_http_path,
    stateless_http=True,
    json_response=True,
)


# Expose Alertmanager context and incident-response guidance to MCP clients.
@mcp.resource("alertmanager://status")
async def get_alertmanager_status() -> str:
    """
    Return a safe summary of the current Alertmanager status.

    Returns:
        The Alertmanager version, cluster status, and uptime.
    """

    return await get_alertmanager().get_status_summary()


@mcp.prompt()
def emergency_silence_flow(alert_name: str) -> str:
    """
    Return instructions for creating an urgent incident silence.

    Args:
        alert_name: Name of the alert that should be silenced.

    Returns:
        A guided workflow for creating a narrowly scoped silence.
    """

    return f"""Help the engineer create an urgent silence for the alert '{alert_name}'.
1. Ask for the engineer's name as it appears in Slack. It will be used as `created_by`.
2. Ask how long the silence should remain active. Use 2h if the engineer does not specify a duration.
3. Ask for a short incident-related comment explaining why the silence is needed and a link to the related Slack thread.
4. Use `list_alerts` with the filter `alertname="{alert_name}"` to find matching alerts.
5. If no matching alerts are found, report that clearly and ask whether the engineer wants to stop or provide a different alert name.
6. If matching alerts are found, summarize them and propose the narrowest useful set of matchers. Do not silence unrelated alerts.
7. Show the proposed matchers, start time, end time, Slack name, and comment. Ask for explicit confirmation before creating the silence.
8. After confirmation, call `create_silence` with RFC3339 timestamps.
9. Report the created silence ID and expiration time. If creation fails, report the error and do not claim that the silence exists."""


# Register Alertmanager alert and silence operations for MCP clients.
@mcp.tool()
async def list_alerts(filters: NonEmptyFilters) -> list[JsonObject]:
    """
    Return all current alerts from Alertmanager.

    Args:
        filters: Alertmanager label matchers, such as `alertname="HighLatency"`.

    Returns:
        The current alerts or an API error.
    """

    async with track_tool("list_alerts"):
        return await get_alertmanager().get_alerts(filters)


@mcp.tool()
async def create_silence(
    matchers: NonEmptyMatchers,
    starts_at: Rfc3339Timestamp,
    ends_at: Rfc3339Timestamp,
    created_by: str,
    comment: str,
) -> JsonObject:
    """
    Create a silence in Alertmanager.

    Args:
        matchers: Label matchers that select alerts for the silence.
        starts_at: Silence start timestamp in RFC3339 format.
        ends_at: Silence end timestamp in RFC3339 format.
        created_by: Name of the engineer as it appears in Slack.
        comment: Reason for creating the silence.

    Returns:
        The created silence or an API error.
    """

    async with track_tool("create_silence"):
        silence = await get_alertmanager().create_silence(matchers, starts_at, ends_at, created_by, comment)
        MCP_SILENCES_CREATED.inc()
        return silence


@mcp.tool()
async def get_silence(silence_id: SilenceId) -> JsonObject:
    """
    Return information about a specific silence.

    Args:
        silence_id: UUID of the silence.

    Returns:
        The requested silence or an API error.
    """

    async with track_tool("get_silence"):
        return await get_alertmanager().get_silence(silence_id)


@mcp.tool()
async def list_silences(filters: NonEmptyFilters) -> list[JsonObject]:
    """
    Return silences from Alertmanager.

    Args:
        filters: Alertmanager label matchers, such as `alertname="HighLatency"`.

    Returns:
        The matching silences or an API error.
    """

    async with track_tool("list_silences"):
        return await get_alertmanager().get_silences(filters)


@mcp.tool()
async def update_silence(
    silence_id: SilenceId,
    matchers: NonEmptyMatchers,
    starts_at: Rfc3339Timestamp,
    ends_at: Rfc3339Timestamp,
    created_by: str,
    comment: str,
) -> JsonObject:
    """
    Update an existing silence.

    Args:
        silence_id: UUID of the silence to overwrite.
        matchers: Label matchers that select alerts for the silence.
        starts_at: Silence start timestamp in RFC3339 format.
        ends_at: Silence end timestamp in RFC3339 format.
        created_by: Name of the engineer as it appears in Slack.
        comment: Reason for updating the silence.

    Returns:
        The updated silence or an API error.
    """

    async with track_tool("update_silence"):
        return await get_alertmanager().update_silence(
            silence_id,
            matchers,
            starts_at,
            ends_at,
            created_by,
            comment,
        )


@mcp.tool()
async def expire_silence(silence_id: SilenceId) -> JsonObject:
    """
    Expire a silence before its scheduled end time.

    Args:
        silence_id: UUID of the silence to expire.

    Returns:
        A success status or an API error.
    """

    async with track_tool("expire_silence"):
        await get_alertmanager().expire_silence(silence_id)
        return {"status": "success"}


@asynccontextmanager
async def server_lifespan(_app: Starlette) -> AsyncGenerator[None]:
    """Keep process-scoped dependencies alive while the ASGI server runs."""

    async with app_lifespan(), mcp.session_manager.run():
        yield


app = Starlette(
    routes=[Mount("/", app=mcp.streamable_http_app())],
    lifespan=server_lifespan,
)


# Run MCP over Streamable HTTP. The ASGI lifespan starts shared dependencies.
if __name__ == "__main__":
    uvicorn.run(app, host=SETTINGS.mcp_host, port=SETTINGS.mcp_port)
