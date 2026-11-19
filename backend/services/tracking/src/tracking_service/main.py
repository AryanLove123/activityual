"""Container entry point:  uvicorn tracking_service.main:app"""
from .api.app import create_app

app = create_app()
