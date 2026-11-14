"""FastAPI authentication dependency built on jwt_verify."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Request

from .config import ApiSettings
from .jwt_verify import TokenError, parse_keys, verify_token
from .problems import unauthenticated


#immutable data holder(class) that represent the currently authenticated user
@dataclass(frozen=True)
class CurrentUser:
    id: UUID


def make_current_user(settings: ApiSettings) -> Callable[..., CurrentUser]:
    keys = parse_keys(settings.jwt_public_keys)

    def current_user(request: Request) -> CurrentUser:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token: 
            raise unauthenticated()

        try: 
            claims = verify_token(token, keys, settings.jwt_issuer, settings.jwt_audience)
            return CurrentUser(id=UUID(claims.user_id))
        except (TokenError, ValueError):
            raise unauthenticated("Invalid or expired token")

    return current_user
