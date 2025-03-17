from http import HTTPStatus
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key, require_invoice_key
from starlette.exceptions import HTTPException

from .crud import (
    get_or_create_settings,
    update_settings,
    create_asset,
    get_assets,
    get_asset,
    create_invoice,
    get_invoice,
    get_user_invoices,
    update_invoice_status,
)
from .models import TaprootSettings, TaprootAsset, TaprootInvoice, TaprootInvoiceRequest
from .wallets.taproot_wallet import TaprootWalletExtension

taproot_assets_api_router = APIRouter(prefix="/api/v1", tags=["taproot_assets"])


@taproot_assets_api_router.get("/settings", status_code=HTTPStatus.OK)
async def api_get_settings(user: User = Depends(check_user_exists)):
    """Get Taproot Assets extension settings."""
    if not user.admin:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Only admin users can access settings",
        )
    
    settings = await get_or_create_settings()
    return settings


@taproot_assets_api_router.put("/settings", status_code=HTTPStatus.OK)
async def api_update_settings(
    settings: TaprootSettings, user: User = Depends(check_user_exists)
):
    """Update Taproot Assets extension settings."""
    if not user.admin:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Only admin users can update settings",
        )
    
    updated_settings = await update_settings(settings)
    return updated_settings


@taproot_assets_api_router.get("/assets", status_code=HTTPStatus.OK)
async def api_list_assets(
    request: Request,
    user: User = Depends(check_user_exists),
):
    """List all Taproot Assets for the current user."""
    # Create a wallet instance to communicate with tapd
    wallet = TaprootWalletExtension()
    
    try:
        # Get assets from tapd
        assets_data = await wallet.list_assets()
        
        # Store assets in database for the user
        stored_assets = []
        for asset_data in assets_data:
            stored_asset = await create_asset(asset_data, user.id)
            stored_assets.append(stored_asset)
        
        return stored_assets
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to list assets: {str(e)}",
        )


@taproot_assets_api_router.get("/assets/{asset_id}", status_code=HTTPStatus.OK)
async def api_get_asset(
    asset_id: str,
    user: User = Depends(check_user_exists),
):
    """Get a specific Taproot Asset by ID."""
    asset = await get_asset(asset_id)
    
    if not asset:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Asset not found",
        )
    
    if asset.user_id != user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Not your asset",
        )
    
    return asset


@taproot_assets_api_router.post("/invoice", status_code=HTTPStatus.CREATED)
async def api_create_invoice(
    data: TaprootInvoiceRequest,
    wallet_info: WalletTypeInfo = Depends(require_invoice_key),
):
    """Create an invoice for a Taproot Asset."""
    try:
        # Create a wallet instance to communicate with tapd
        wallet = TaprootWalletExtension()
        
        # Create the invoice using the TaprootWalletExtension
        invoice_response = await wallet.create_invoice(
            amount=data.amount,
            memo=data.memo or "Taproot Asset Transfer",
            asset_id=data.asset_id,
            expiry=data.expiry,
        )
        
        if not invoice_response.ok:
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice: {invoice_response.error_message}",
            )
        
        # Extract data from the invoice response
        payment_hash = invoice_response.payment_hash
        payment_request = invoice_response.payment_request
        buy_quote = invoice_response.extra.get("buy_quote") if invoice_response.extra else None
        
        # Parse the original BOLT11 invoice to get the correct satoshi amount
        from lnbits import bolt11
        try:
            decoded_invoice = bolt11.decode(payment_request)
            satoshi_amount_msat = decoded_invoice.amount_msat
            satoshi_amount = satoshi_amount_msat // 1000 if satoshi_amount_msat is not None else 0
        except Exception:
            satoshi_amount = data.amount  # Fallback to asset amount if decoding fails
        
        # Create an invoice record in the database
        invoice = await create_invoice(
            asset_id=data.asset_id,
            asset_amount=data.amount,
            satoshi_amount=satoshi_amount,
            payment_hash=payment_hash,
            payment_request=payment_request,
            user_id=wallet_info.wallet.user,
            wallet_id=wallet_info.wallet.id,
            memo=data.memo,
            expiry=data.expiry,
            buy_quote=buy_quote,
        )
        
        return {
            "payment_hash": payment_hash,
            "payment_request": payment_request,
            "asset_id": data.asset_id,
            "asset_amount": data.amount,
            "satoshi_amount": satoshi_amount,
            "accepted_buy_quote": buy_quote,
            "checking_id": invoice.id,
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Taproot Asset invoice: {str(e)}",
        )


@taproot_assets_api_router.get("/invoices", status_code=HTTPStatus.OK)
async def api_list_invoices(
    user: User = Depends(check_user_exists),
):
    """List all Taproot Asset invoices for the current user."""
    invoices = await get_user_invoices(user.id)
    return invoices


@taproot_assets_api_router.get("/invoices/{invoice_id}", status_code=HTTPStatus.OK)
async def api_get_invoice(
    invoice_id: str,
    user: User = Depends(check_user_exists),
):
    """Get a specific Taproot Asset invoice by ID."""
    invoice = await get_invoice(invoice_id)
    
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Invoice not found",
        )
    
    if invoice.user_id != user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Not your invoice",
        )
    
    return invoice


@taproot_assets_api_router.put("/invoices/{invoice_id}/status", status_code=HTTPStatus.OK)
async def api_update_invoice_status(
    invoice_id: str,
    status: str = Query(..., description="New status for the invoice"),
    user: User = Depends(check_user_exists),
):
    """Update the status of a Taproot Asset invoice."""
    invoice = await get_invoice(invoice_id)
    
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Invoice not found",
        )
    
    if invoice.user_id != user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Not your invoice",
        )
    
    if status not in ["pending", "paid", "expired", "cancelled"]:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Invalid status",
        )
    
    updated_invoice = await update_invoice_status(invoice_id, status)
    return updated_invoice
