"""Settings read from environment variables.

pydantic-settings validates types at start-up, so a typo stops the container immediately
instead of failing later in production. Secrets are never given defaults.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    service_name: str = "service"
    environment: str = "local"
    enable_docs: bool = True
    log_level: str = "INFO"


class ApiSettings(CommonSettings):
    """Settings for a service that serves authenticated API calls and uses PostgresSQL."""

    database_url: SecretStr | None = None
    jwt_public_keys: str = "{}"
    jwt_issuer: str = "activityual-auth"
    jwt_audience: str = "activityual-api"
    db_pool_size: int = 2
    db_max_overflow: int = 1
    db_pool_timeout: float = 5.0
