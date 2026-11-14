"""Container entry point:  uvicorn auth_service.main:app  (settings come from environment variables)."""
from .app import create_app

app = create_app()
