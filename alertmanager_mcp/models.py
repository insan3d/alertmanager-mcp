"""Define shared Alertmanager MCP models."""

from typing import TypedDict

# Keep API payloads JSON-compatible without falling back to Any.
type JsonScalar = bool | float | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type Matcher = dict[str, bool | str]


class ErrorResponse(TypedDict):
    """Describe a consistent Alertmanager API error."""

    error: str
    code: int | None
