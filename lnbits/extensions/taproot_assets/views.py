from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer

taproot_assets_router = APIRouter(prefix="", tags=["taproot_assets"])


def taproot_assets_renderer():
    return template_renderer(["taproot_assets/templates"])


@taproot_assets_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    """
    Taproot Assets extension home page.
    """
    return taproot_assets_renderer().TemplateResponse(
        "taproot_assets/index.html",
        {"request": request, "user": user.json()},
    )


@taproot_assets_router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request, user: User = Depends(check_user_exists)):
    """
    Taproot Assets extension settings page.
    """
    return taproot_assets_renderer().TemplateResponse(
        "taproot_assets/settings.html",
        {"request": request, "user": user.json()},
    )
