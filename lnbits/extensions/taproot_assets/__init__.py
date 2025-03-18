import asyncio
from fastapi import APIRouter
from loguru import logger
from .crud import db
from .views import taproot_assets_router
from .views_api import taproot_assets_api_router

# Create router with prefix for the extension
taproot_assets_ext = APIRouter(prefix="/taproot_assets", tags=["taproot_assets"])

# Include the routers
taproot_assets_ext.include_router(taproot_assets_router)
taproot_assets_ext.include_router(taproot_assets_api_router)

# Define static files with the correct naming pattern
taproot_assets_static_files = [
    {
        "path": "/taproot_assets/static",
        "name": "taproot_assets_static",
        "mount_point": "/taproot_assets/static",  # Added mount_point
    }
]

# List for scheduled tasks
scheduled_tasks: list[asyncio.Task] = []

def taproot_assets_start():
    """Start scheduled tasks including the invoice payment listener."""
    from lnbits.tasks import create_permanent_unique_task
    from .tasks import wait_for_paid_invoices
    
    # Create and start the invoice payment listener task
    task = create_permanent_unique_task("taproot_assets_payment_listener", wait_for_paid_invoices)
    scheduled_tasks.append(task)
    
    logger.info("Taproot Assets extension started with payment listener")

def taproot_assets_stop():
    """Stop any scheduled tasks."""
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)
    
    logger.info("Taproot Assets extension stopped")

# Make sure db is properly exposed
def taproot_assets_createdb():
    """Initialize the database schema."""
    from . import migrations
    return (db, [migrations])

# Items to export - fixed syntax
__all__ = [
    "db",
    "taproot_assets_ext",
    "taproot_assets_static_files",
    "taproot_assets_start",
    "taproot_assets_stop",
    "taproot_assets_createdb",
]
