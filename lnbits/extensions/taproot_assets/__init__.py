import asyncio
from typing import List

from fastapi import APIRouter

from .crud import db
from .views import taproot_assets_router
from .views_api import taproot_assets_api_router

# Define static files
taproot_assets_static_files = [
    {
        "path": "/taproot_assets/static",
        "name": "taproot_assets_static",
    }
]

# Create router
taproot_assets_ext: APIRouter = APIRouter(prefix="/taproot_assets", tags=["taproot_assets"])
taproot_assets_ext.include_router(taproot_assets_router)
taproot_assets_ext.include_router(taproot_assets_api_router)

# List for scheduled tasks
scheduled_tasks: List[asyncio.Task] = []

def taproot_assets_stop():
    """Stop any scheduled tasks."""
    for task in scheduled_tasks:
        task.cancel()

def taproot_assets_start():
    """Start any scheduled tasks."""
    pass

__all__ = [
    "taproot_assets_ext",
    "taproot_assets_static_files",
    "taproot_assets_stop",
    "taproot_assets_start",
    "db",
]
