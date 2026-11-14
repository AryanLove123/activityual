import json

from activityual_common.app_factory import create_service_app
from activityual_common.db import (
    make_engine,
    make_session_factory,
    session_dependency,
)
from activityual_common.security import make_current_user
from fastapi import FastAPI
from sqlalchemy import Engine

from .routes import build_router
from .settings import AuthSettings
from .tokens import TokenIssuer


def create_app(settings: AuthSettings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or AuthSettings()
    if engine is None:
        if settings.database_url is None:
            raise RuntimeError("DATABASE_URL is required")
        engine = make_engine(settings.database_url.get_secret_value(), pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, pool_timeout=settings.db_pool_timeout)

    if settings.jwt_private_key is None: 
        raise RuntimeError("JWT_PRIVATE_KEY is required")
    issuer = TokenIssuer(settings.jwt_private_key.get_secret_value(), settings.jwt_kid, settings.jwt_issuer,
                         settings.jwt_audience, settings.access_token_minutes)

    verify_settings = settings.model_copy(update = {"jwt_public_keys": json.dumps({issuer.kid: issuer.public_pem})})
    factory = make_session_factory(engine)
    app = create_service_app(title="Activityual Auth", collection="auth", settings=settings)
    app.include_router(build_router(session_dependency(lambda: factory), make_current_user(verify_settings), issuer))
    app.state.engine = engine
    return app