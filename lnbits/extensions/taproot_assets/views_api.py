# /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/views_api.py
from http import HTTPStatus
from typing import List, Optional
import grpc
import traceback
import sys

from fastapi import APIRouter, Depends, Query, Request
from lnbits.core.crud import get_user, get_wallet, get_wallet_for_key
from lnbits.core.services import update_wallet_balance, pay_invoice as core_pay_invoice
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key, require_invoice_key
from starlette.exceptions import HTTPException
from loguru import logger
from pydantic import BaseModel
import bolt11  # Added import for bolt11

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
    get_fee_transactions
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
    default_sat_fee: Optional[int] = None  # Added default_sat_fee setting


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
    logger.info(f"Starting asset listing for user {user.id}")
    try:
        # Create a wallet instance to communicate with tapd
        wallet = TaprootWalletExtension()

        # Get assets from tapd
        assets_data = await wallet.list_assets()
        logger.info(f"Retrieved {len(assets_data)} assets from tapd")

        # Return assets directly without storing in database
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
        try:
            taproot_wallet = TaprootWalletExtension()
        except Exception as e:
            logger.error(f"Failed to create TaprootWalletExtension: {str(e)}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize Taproot wallet: {str(e)}",
            )

        # Create the invoice using the TaprootWalletExtension
        try:
            invoice_response = await taproot_wallet.create_invoice(
                amount=data.amount,
                memo=data.memo or "Taproot Asset Transfer",
                asset_id=data.asset_id,
                expiry=data.expiry,
                peer_pubkey=data.peer_pubkey,  # Pass peer_pubkey to create_invoice
            )
        except Exception as e:
            logger.error(f"Failed in taproot_wallet.create_invoice: {str(e)}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice in wallet: {str(e)}",
            )

        if not invoice_response.ok:
            logger.error(f"Invoice creation failed: {invoice_response.error_message}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice: {invoice_response.error_message}",
            )

        # Extract data from the invoice response
        payment_request = invoice_response.payment_request
        
        # Extract payment hash from the BOLT11 payment request (primary method)
        try:
            decoded = bolt11.decode(payment_request)
            payment_hash = decoded.payment_hash
            logger.info(f"Extracted payment hash from BOLT11: {payment_hash}")
        except Exception as e:
            logger.error(f"Failed to extract payment hash from BOLT11: {e}")
            
            # Fallback to the response's payment_hash if extraction fails
            payment_hash = invoice_response.payment_hash
            logger.info(f"Falling back to response payment_hash: {payment_hash or 'None'}")

        # Ensure we have a valid payment hash
        if not payment_hash:
            logger.error("No payment hash available - cannot create invoice!")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail="Failed to get payment hash for invoice",
            )

        # Get satoshi fee from settings (for database record, not deduction)
        satoshi_amount = taproot_settings.default_sat_fee

        # Create an invoice record in the database
        try:
            invoice = await create_invoice(
                asset_id=data.asset_id,
                asset_amount=data.amount,
                satoshi_amount=satoshi_amount,
                payment_hash=payment_hash,
                payment_request=payment_request,
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                memo=data.memo,
                expiry=data.expiry,
            )
        except Exception as e:
            logger.error(f"Failed to create invoice record: {str(e)}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to store invoice in database: {str(e)}",
            )

        # Prepare final response
        try:
            response_data = {
                "payment_hash": payment_hash,
                "payment_request": payment_request,
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "satoshi_amount": satoshi_amount,
                "checking_id": invoice.id if invoice else "",
            }
            logger.info(f"Successfully created invoice for asset_id={data.asset_id}")
            return response_data
        except Exception as e:
            logger.error(f"Failed to prepare response: {str(e)}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to format response: {str(e)}",
            )
    except Exception as e:
        # Handle common error cases with user-friendly messages
        if "multiple asset channels found for asset" in str(e) and "please specify the peer pubkey" in str(e):
            detail = f"Multiple channels found for asset {data.asset_id}. Please select a specific channel from the asset list."
        elif isinstance(e, grpc.RpcError) and "no asset channel balance found for asset" in str(e):
            detail = f"No channel balance found for asset {data.asset_id}. You need to create a channel with this asset first."
        else:
            detail = f"Failed to create Taproot Asset invoice: {str(e)}"
            
        logger.error(f"Error creating invoice: {str(e)}")
        
        # Don't propagate HTTPExceptions
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
    logger.info(f"Paying invoice payment_request={data.payment_request[:30]}...")
    try:
        user_wallet = wallet.wallet
        taproot_wallet = TaprootWalletExtension()
        # Use a higher fee limit for routing through third nodes
        fee_limit_sats = max(taproot_settings.default_sat_fee, 10)  # Minimum 10 sats for routing
        logger.info(f"Using fee_limit_sats={fee_limit_sats} for payment")

        # Decode the invoice to get the amount (for logging purposes only)
        decoded_invoice = bolt11.decode(data.payment_request)
        invoice_amount_sats = int(decoded_invoice.amount_msat / 1000)
        logger.info(f"Invoice amount: {invoice_amount_sats} sats")

        # No longer deducting from LNbits wallet balance for Taproot Asset transfers

        # Pay the invoice using litd (tapd's LND node)
        try:
            # Log if peer_pubkey is provided
            if data.peer_pubkey:
                logger.info(f"Using peer_pubkey for payment: {data.peer_pubkey}")

            logger.info("Starting payment process - this will wait for payment completion")
            payment = await taproot_wallet.pay_asset_invoice(
                invoice=data.payment_request,
                fee_limit_sats=fee_limit_sats,
                peer_pubkey=data.peer_pubkey  # Pass peer_pubkey to the wallet
            )

            if not payment.ok:
                logger.error(f"Payment failed: {payment.error_message}")
                raise Exception(f"Payment failed: {payment.error_message}")

            logger.info(f"Payment completed successfully: {payment.checking_id}")
        except Exception as e:
            # No need to refund since we're not deducting from wallet balance anymore
            logger.error(f"Payment error: {str(e)}")
            raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Failed to pay invoice: {str(e)}")

        # Calculate routing fees for logging purposes only
        routing_fees_sats = payment.fee_msat // 1000 if payment.fee_msat else 0  # Convert msat to sat
        if routing_fees_sats > 0:
            logger.info(f"Routing fees: {routing_fees_sats} sats (not deducted from wallet)")

        # Prepare response
        response_data = {
            "success": True,
            "payment_hash": payment.checking_id,
            "preimage": payment.preimage or "",
            "fee_msat": payment.fee_msat or 0,
            "sat_fee_paid": 0,  # No additional service fee
            "routing_fees_sats": routing_fees_sats
        }
        logger.info(f"Successfully paid invoice (routing fees: {routing_fees_sats} sats)")
        return response_data

    except Exception as e:
        # Don't catch HTTPExceptions - let them propagate with their status codes
        if isinstance(e, HTTPException):
            raise

        # Provide a user-friendly message for common errors
        detail = f"Failed to pay Taproot Asset invoice: {str(e)}"
        if isinstance(e, grpc.RpcError) and "no asset channel balance found for asset" in str(e):
            detail = "Insufficient channel balance for this asset."

        logger.error(f"Error paying invoice: {str(e)}")
        
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=detail,
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
        logger.error(f"Error in api_list_invoices: {str(e)}")
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
