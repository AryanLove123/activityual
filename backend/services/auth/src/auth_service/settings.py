from activityual_common.config import ApiSettings
from pydantic import SecretStr, field_validator


class AuthSettings(ApiSettings):
    service_name: str = "auth-service"
    jwt_private_key: SecretStr | None = None
    jwt_kid: str = "dev"
    access_token_minutes: int = 30

    @field_validator("jwt_private_key", mode="after")
    @classmethod
    def _expand_newlines(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None:
            return v
        return SecretStr(v.get_secret_value().replace("\\n", "\n"))
