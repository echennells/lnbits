from http import HTTPStatus
from typing import List, Optional
import grpc
import re

from fastapi import APIRouter, Depends, Query, Request
from lnbits.core.crud import get_user, get_wallet, get_wallet_for_key
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key, require_invoice_key
from starlette.exceptions import HTTPException
from loguru import logger
from pydantic import BaseModel
import bolt11

from .crud import (
    get_or_create_settings,
    update_settings,
    create_asset,
    get_assets,
    get_asset,
    create_invoice,
    get_invoice,
    get_invoice_by_payment_hash,
    get_user_invoices,
    update_invoice_status,
    create_fee_transaction,
    get_fee_transactions,
    create_payment_record,
    get_user_payments
)
from .models import TaprootSettings, TaprootAsset, TaprootInvoice, TaprootInvoiceRequest, TaprootPaymentRequest
from .wallets.taproot_wallet import TaprootWalletExtension
from .tapd_settings import taproot_settings

# The parent router in __init__.py already adds the "/taproot_assets" prefix
# So we only need to add the API path here
taproot_assets_api_router = APIRouter(prefix="/api/v1/taproot", tags=["taproot_assets"])


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


class TapdSettingsUpdate(BaseModel):
    tapd_host: Optional[str] = None
    tapd_network: Optional[str] = None
    tapd_tls_cert_path: Optional[str] = None
    tapd_macaroon_path: Optional[str] = None
    tapd_macaroon_hex: Optional[str] = None
    lnd_macaroon_path: Optional[str] = None
    lnd_macaroon_hex: Optional[str] = None
    default_sat_fee: Optional[int] = None


@taproot_assets_api_router.put("/tapd-settings", status_code=HTTPStatus.OK)
async def api_update_tapd_settings(
    data: TapdSettingsUpdate, user: User = Depends(check_user_exists)
):
    """Update Taproot daemon settings."""
    if not user.admin:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Only admin users can update Taproot daemon settings",
        )

    # Update only the settings that were provided
    for key, value in data.dict(exclude_unset=True).items():
        if hasattr(taproot_settings, key) and value is not None:
            setattr(taproot_settings, key, value)

    # Save the updated settings
    taproot_settings.save()

    return {
        "success": True,
        "settings": {key: getattr(taproot_settings, key) for key in data.dict(exclude_unset=True) if hasattr(taproot_settings, key)}
    }


@taproot_assets_api_router.get("/tapd-settings", status_code=HTTPStatus.OK)
async def api_get_tapd_settings(user: User = Depends(check_user_exists)):
    """Get Taproot daemon settings."""
    if not user.admin:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Only admin users can view Taproot daemon settings",
        )

    # Convert settings to a dictionary
    settings_dict = {}
    for key in dir(taproot_settings):
        if not key.startswith('_') and not callable(getattr(taproot_settings, key)) and key not in ['extension_dir', 'config_path', 'config']:
            settings_dict[key] = getattr(taproot_settings, key)

    return settings_dict


@taproot_assets_api_router.get("/listassets", status_code=HTTPStatus.OK)
async def api_list_assets(
    request: Request,
    user: User = Depends(check_user_exists),
):
    """List all Taproot Assets for the current user."""
    try:
        # Create a wallet instance to communicate with tapd
        wallet = TaprootWalletExtension()

        # Get assets from tapd
        assets_data = await wallet.list_assets()
        
        return assets_data
    except Exception as e:
        logger.error(f"Failed to list assets: {str(e)}")
        return []  # Return empty list on error


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
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Create an invoice for a Taproot Asset."""
    logger.info(f"Creating invoice for asset_id={data.asset_id}, amount={data.amount}")
    try:
        # Create a wallet instance to communicate with tapd
        taproot_wallet = TaprootWalletExtension()

        # Create the invoice
        invoice_response = await taproot_wallet.create_invoice(
            amount=data.amount,
            memo=data.memo or "Taproot Asset Transfer",
            asset_id=data.asset_id,
            expiry=data.expiry,
            peer_pubkey=data.peer_pubkey,
        )

        if not invoice_response.ok:
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice: {invoice_response.error_message}",
            )

        # Get satoshi fee from settings
        satoshi_amount = taproot_settings.default_sat_fee

        # Create invoice record in the database
        invoice = await create_invoice(
            asset_id=data.asset_id,
            asset_amount=data.amount,
            satoshi_amount=satoshi_amount,
            payment_hash=invoice_response.payment_hash,
            payment_request=invoice_response.payment_request,
            user_id=wallet.wallet.user,
            wallet_id=wallet.wallet.id,
            memo=data.memo or f"Taproot Asset Transfer: {data.asset_id}",
            expiry=data.expiry,
        )

        # Return response data
        return {
            "payment_hash": invoice_response.payment_hash,
            "payment_request": invoice_response.payment_request,
            "asset_id": data.asset_id,
            "asset_amount": data.amount,
            "satoshi_amount": satoshi_amount,
            "checking_id": invoice.id,
        }
        
    except Exception as e:
        # Create user-friendly error messages for common issues
        if "multiple asset channels found" in str(e) and "please specify the peer pubkey" in str(e):
            detail = f"Multiple channels found for asset {data.asset_id}. Please select a specific channel from the asset list."
        elif isinstance(e, grpc.RpcError) and "no asset channel balance found for asset" in str(e):
            detail = f"No channel balance found for asset {data.asset_id}. You need to create a channel with this asset first."
        else:
            detail = f"Failed to create Taproot Asset invoice: {str(e)}"

        logger.error(f"Error creating invoice: {str(e)}")

        # Don't re-wrap HTTPExceptions
        if isinstance(e, HTTPException):
            raise

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=detail,
        )


@taproot_assets_api_router.post("/pay", status_code=HTTPStatus.OK)
async def api_pay_invoice(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Pay a Taproot Asset invoice."""
    try:
        # Initialize taproot wallet
        taproot_wallet = TaprootWalletExtension()
        
        # Set fee limit
        fee_limit_sats = max(taproot_settings.default_sat_fee, 10)
        
        # Make the payment
        payment = await taproot_wallet.pay_asset_invoice(
            invoice=data.payment_request,
            fee_limit_sats=fee_limit_sats,
            peer_pubkey=data.peer_pubkey
        )

        # Verify payment success
        if not payment.ok:
            raise Exception(f"Payment failed: {payment.error_message}")
            
        # Calculate routing fees
        routing_fees_sats = payment.fee_msat // 1000 if payment.fee_msat else 0
        
        # Get payment details
        payment_hash = payment.checking_id
        preimage = payment.preimage or ""
        
        # Record the payment
        try:
            # Extract asset info from payment extra data
            asset_id = payment.extra.get("asset_id", "")
            asset_amount = payment.extra.get("asset_amount", 0)
            
            # Create descriptive memo
            memo = f"Taproot Asset Transfer"
            
            # Record payment with available information
            await create_payment_record(
                payment_hash=payment_hash,
                payment_request=data.payment_request,
                asset_id=asset_id,
                asset_amount=asset_amount,
                fee_sats=routing_fees_sats,
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                memo=memo,
                preimage=preimage
            )
        except Exception as e:
            # Don't fail if payment record creation fails
            logger.error(f"Failed to store payment record: {str(e)}")
        
        # Return success response
        return {
            "success": True,
            "payment_hash": payment_hash,
            "preimage": preimage,
            "fee_msat": payment.fee_msat or 0,
            "sat_fee_paid": 0,  # No service fee
            "routing_fees_sats": routing_fees_sats,
            "asset_amount": asset_amount
        }
    
    except HTTPException:
        # Let HTTP exceptions propagate
        raise
        
    except Exception as e:
        # Create user-friendly error message
        detail = str(e)
        
        if "no asset channel balance found for asset" in str(e):
            detail = "Insufficient channel balance for this asset."
            
        logger.error(f"Payment error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=detail)


@taproot_assets_api_router.get("/payments", status_code=HTTPStatus.OK)
async def api_list_payments(
    user: User = Depends(check_user_exists),
):
    """List all Taproot Asset payments for the current user."""
    try:
        payments = await get_user_payments(user.id)
        return payments
    except Exception as e:
        logger.error(f"Error retrieving payments: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve payments: {str(e)}",
        )


@taproot_assets_api_router.get("/fee-transactions", status_code=HTTPStatus.OK)
async def api_list_fee_transactions(
    user: User = Depends(check_user_exists),
):
    """List all fee transactions for the current user."""
    # If admin, can view all transactions, otherwise just their own
    if user.admin:
        transactions = await get_fee_transactions()
    else:
        transactions = await get_fee_transactions(user.id)

    return transactions


@taproot_assets_api_router.get("/invoices", status_code=HTTPStatus.OK)
async def api_list_invoices(
    user: User = Depends(check_user_exists),
):
    """List all Taproot Asset invoices for the current user."""
    try:
        invoices = await get_user_invoices(user.id)
        return invoices
    except Exception as e:
        logger.error(f"Error retrieving invoices: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve invoices: {str(e)}",
        )


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
