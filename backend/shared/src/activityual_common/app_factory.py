"""Creates a FastAPI app with the conventions every service shares."""

from fastapi import FastAPI

from .config import CommonSettings
from .logging import configure_logging


def create_service_app(
        *, 
        title: str, 
        collection: str,
        settings: CommonSettings | None = None,
) -> FastAPI:
    settings = settings or CommonSettings()
    configure_logging(settings.service_name or collection, settings.log_level)
    docs = settings.enable_docs
    app = FastAPI(
        title = title,
        docs_url=f"/api/{collection}/docs" if docs else None,
        openapi_url=f"/api/{collection}/openapi.json" if docs else None,
        redoc_url=None,
        redirect_slashes=False,
    )

    return app