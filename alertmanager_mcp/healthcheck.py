"""Run an end-to-end healthcheck against the local MCP server."""

import asyncio
import logging
from http import HTTPStatus
from typing import Final
from urllib.request import urlopen

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import AnyUrl

from alertmanager_mcp.config import SETTINGS

LOGGER: Final = logging.getLogger(__name__)
MCP_HEALTHCHECK_URL: Final = SETTINGS.mcp_healthcheck_url or f"http://127.0.0.1:{SETTINGS.mcp_port}{SETTINGS.mcp_http_path}"
METRICS_HEALTHCHECK_URL: Final = SETTINGS.metrics_healthcheck_url or f"http://127.0.0.1:{SETTINGS.metrics_port}/metrics"
EXPECTED_TOOLS: Final = {
    "create_silence",
    "expire_silence",
    "get_silence",
    "list_alerts",
    "list_silences",
    "update_silence",
}


async def _check_mcp() -> None:
    """Verify MCP initialization, tool discovery, and Alertmanager access."""

    async with (
        httpx.AsyncClient(timeout=SETTINGS.healthcheck_timeout_seconds) as http_client,
        streamable_http_client(
            MCP_HEALTHCHECK_URL,
            http_client=http_client,
        ) as (read_stream, write_stream, _),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        if tool_names != EXPECTED_TOOLS:
            msg = f"Unexpected MCP tools: {sorted(tool_names)}"
            raise RuntimeError(msg)

        status = await session.read_resource(AnyUrl("alertmanager://status"))
        if not any("Alertmanager version:" in getattr(content, "text", "") for content in status.contents):
            msg = "Alertmanager status resource returned no version"
            raise RuntimeError(msg)


def _check_metrics() -> None:
    """Verify that the Prometheus metrics listener is reachable."""

    with urlopen(METRICS_HEALTHCHECK_URL, timeout=SETTINGS.healthcheck_timeout_seconds) as response:  # noqa: S310
        if response.status != HTTPStatus.OK:
            msg = f"Metrics endpoint returned HTTP {response.status}"
            raise RuntimeError(msg)


def main() -> int:
    """Return a process status suitable for a container healthcheck."""

    try:
        asyncio.run(_check_mcp())
        _check_metrics()

    except Exception:
        LOGGER.exception("Healthcheck failed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
