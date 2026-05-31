"""Define shared Alertmanager MCP models."""

from datetime import datetime
from typing import Annotated, NotRequired, TypedDict
from uuid import UUID

from pydantic import AwareDatetime, Field

# Keep API payloads JSON-compatible without falling back to Any.
type JsonScalar = bool | float | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type SilenceId = UUID
type Rfc3339Timestamp = Annotated[datetime, AwareDatetime]
type NonEmptyFilters = Annotated[list[str], Field(min_length=1)]


class Matcher(TypedDict):
    """Describe an Alertmanager silence matcher."""

    name: str
    value: str
    is_regex: bool
    is_equal: NotRequired[bool]


type NonEmptyMatchers = Annotated[list[Matcher], Field(min_length=1)]
