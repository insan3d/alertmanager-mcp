"""Load Alertmanager MCP configuration from environment variables."""

from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

type PositiveFloat = Annotated[float, Field(gt=0)]
type PositiveInt = Annotated[int, Field(gt=0)]
type Port = Annotated[int, Field(ge=1, le=65535)]


class Settings(BaseSettings):
    """Describe validated server configuration."""

    model_config = SettingsConfigDict(frozen=True)

    alertmanager_url: str = "http://localhost:9093"
    alertmanager_connect_timeout_seconds: PositiveFloat = 5.0
    alertmanager_read_timeout_seconds: PositiveFloat = 10.0
    alertmanager_write_timeout_seconds: PositiveFloat = 10.0
    alertmanager_pool_timeout_seconds: PositiveFloat = 5.0
    alertmanager_max_connections: PositiveInt = 100
    alertmanager_max_keepalive_connections: PositiveInt = 20
    alertmanager_keepalive_expiry_seconds: PositiveFloat = 5.0
    mcp_name: str = "Alertmanager API Proxy"
    mcp_host: str = "127.0.0.1"
    mcp_port: Port = 8000
    mcp_http_path: str = "/mcp"
    metrics_host: str = "127.0.0.1"
    metrics_port: Port = 8001
    mcp_healthcheck_url: str | None = None
    metrics_healthcheck_url: str | None = None
    healthcheck_timeout_seconds: PositiveFloat = 5.0

    @property
    def alertmanager_api_url(self) -> str:
        """Return the Alertmanager v2 API base URL."""

        return f"{self.alertmanager_url.rstrip('/')}/api/v2"


SETTINGS = Settings()
