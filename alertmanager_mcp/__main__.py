#!/usr/bin/env python3

"""Expose Alertmanager operations through an HTTP MCP server."""

from contextlib import suppress

from mcp.server.fastmcp import FastMCP
from prometheus_client import start_http_server

from alertmanager_mcp.config import MCP_HOST, MCP_HTTP_PATH, MCP_NAME, MCP_PORT, METRICS_HOST, METRICS_PORT
from alertmanager_mcp.models import JsonObject, Matcher
from alertmanager_mcp.runtime import (
    MCP_SILENCES_CREATED,
    MCP_TOOL_REQUESTS,
    AppMcpContext,
    app_lifespan,
    as_json_error,
    as_json_matchers,
    get_error,
    get_http_client,
    get_json_object,
    get_json_objects,
    is_success,
    make_request,
)

# Configure the MCP server's Streamable HTTP listener.
mcp = FastMCP(
    MCP_NAME,
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_HTTP_PATH,
    lifespan=app_lifespan,
)


# Expose Alertmanager context and incident-response guidance to MCP clients.
@mcp.resource("alertmanager://status")
async def get_alertmanager_status(ctx: AppMcpContext) -> str:
    """
    Return the current Alertmanager configuration.

    Args:
        ctx: Current MCP request context.

    Returns:
        The Alertmanager configuration or an API error message.
    """

    response = await make_request(get_http_client(ctx), "GET", "status", "status")
    if not is_success(response):
        error = get_error(response)
        return f"Failed to get status: {error['error']}"

    data = get_json_object(response)
    config = data.get("config")
    if isinstance(config, dict):
        original_config = config.get("original")
        if isinstance(original_config, str):
            return f"Alertmanager Config:\n{original_config}"

    return "Alertmanager Config:\nNo config found"


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
4. Use `list_alerts` to find active alerts whose `alertname` label matches '{alert_name}'.
5. If no matching alerts are found, report that clearly and ask whether the engineer wants to stop or provide a different alert name.
6. If matching alerts are found, summarize them and propose the narrowest useful set of matchers. Do not silence unrelated alerts.
7. Show the proposed matchers, start time, end time, Slack name, and comment. Ask for explicit confirmation before creating the silence.
8. After confirmation, call `create_silence` with RFC3339 timestamps.
9. Report the created silence ID and expiration time. If creation fails, report the error and do not claim that the silence exists."""


# Register Alertmanager alert and silence operations for MCP clients.
@mcp.tool()
async def list_alerts(ctx: AppMcpContext) -> list[JsonObject]:
    """
    Return all current alerts from Alertmanager.

    Args:
        ctx: Current MCP request context.

    Returns:
        The current alerts or an API error.
    """

    tool_name = "list_alerts"
    response = await make_request(
        get_http_client(ctx),
        "GET",
        "alerts",
        "alerts",
        params={"active": "true", "silenced": "true", "inhibited": "true"},
    )

    if not is_success(response):
        error = get_error(response)
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        return [as_json_error(error)]

    MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()
    return get_json_objects(response)


@mcp.tool()
async def create_silence(
    matchers: list[Matcher],
    starts_at: str,
    ends_at: str,
    created_by: str,
    comment: str,
    ctx: AppMcpContext,
) -> JsonObject:
    """
    Create a silence in Alertmanager.

    Args:
        matchers: Label matchers that select alerts for the silence.
        starts_at: Silence start timestamp in RFC3339 format.
        ends_at: Silence end timestamp in RFC3339 format.
        created_by: Name of the engineer as it appears in Slack.
        comment: Reason for creating the silence.
        ctx: Current MCP request context.

    Returns:
        The created silence or an API error.
    """

    tool_name = "create_silence"
    payload: JsonObject = {
        "matchers": as_json_matchers(matchers),
        "startsAt": starts_at,
        "endsAt": ends_at,
        "createdBy": created_by,
        "comment": comment,
    }

    response = await make_request(
        get_http_client(ctx),
        "POST",
        "silences",
        "silences",
        json=payload,
    )

    if not is_success(response):
        error = get_error(response)
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        return as_json_error(error)

    MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()
    MCP_SILENCES_CREATED.inc()
    return get_json_object(response)


@mcp.tool()
async def get_silence(silence_id: str, ctx: AppMcpContext) -> JsonObject:
    """
    Return information about a specific silence.

    Args:
        silence_id: UUID of the silence.
        ctx: Current MCP request context.

    Returns:
        The requested silence or an API error.
    """

    tool_name = "get_silence"
    response = await make_request(
        get_http_client(ctx),
        "GET",
        f"silence/{silence_id}",
        "silence/{silence_id}",
    )

    if not is_success(response):
        error = get_error(response)
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        return as_json_error(error)

    MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()
    return get_json_object(response)


@mcp.tool()
async def list_silences(ctx: AppMcpContext, filter_query: str | None = None) -> list[JsonObject]:
    """
    Return silences from Alertmanager.

    Args:
        ctx: Current MCP request context.
        filter_query: Optional Alertmanager filter, such as `status="active"`.

    Returns:
        The matching silences or an API error.
    """

    tool_name = "list_silences"
    params = {"filter": filter_query} if filter_query else {}
    response = await make_request(
        get_http_client(ctx),
        "GET",
        "silences",
        "silences",
        params=params,
    )

    if not is_success(response):
        error = get_error(response)
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        return [as_json_error(error)]

    MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()
    return get_json_objects(response)


@mcp.tool()
async def update_silence(
    silence_id: str,
    matchers: list[Matcher],
    starts_at: str,
    ends_at: str,
    created_by: str,
    comment: str,
    ctx: AppMcpContext,
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
        ctx: Current MCP request context.

    Returns:
        The updated silence or an API error.
    """

    tool_name = "update_silence"
    payload: JsonObject = {
        "id": silence_id,
        "matchers": as_json_matchers(matchers),
        "startsAt": starts_at,
        "endsAt": ends_at,
        "createdBy": created_by,
        "comment": comment,
    }

    response = await make_request(
        get_http_client(ctx),
        "POST",
        "silences",
        "silences",
        json=payload,
    )

    if not is_success(response):
        error = get_error(response)
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        return as_json_error(error)

    MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()
    return get_json_object(response)


@mcp.tool()
async def expire_silence(silence_id: str, ctx: AppMcpContext) -> JsonObject:
    """
    Expire a silence before its scheduled end time.

    Args:
        silence_id: UUID of the silence to expire.
        ctx: Current MCP request context.

    Returns:
        A success status or an API error.
    """

    tool_name = "expire_silence"
    response = await make_request(
        get_http_client(ctx),
        "DELETE",
        f"silence/{silence_id}",
        "silence/{silence_id}",
    )

    if not is_success(response):
        error = get_error(response)
        MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="error").inc()
        return as_json_error(error)

    MCP_TOOL_REQUESTS.labels(tool_name=tool_name, status="success").inc()
    return {"status": "success"}


# Run metrics on a separate listener while MCP serves Streamable HTTP requests.
if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        _ = start_http_server(METRICS_PORT, addr=METRICS_HOST)
        mcp.run(transport="streamable-http")
