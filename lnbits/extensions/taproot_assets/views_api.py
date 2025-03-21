from http import HTTPStatus
from typing import List, Optional
import grpc
import traceback
import sys

from fastapi import APIRouter, Depends, Query, Request
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key, require_invoice_key
from starlette.exceptions import HTTPException
from loguru import logger
from pydantic import BaseModel

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
    tapd_rfq_price_oracle_address: Optional[str] = None
    tapd_rfq_mock_oracle_assets_per_btc: Optional[int] = None
    tapd_rfq_skip_accept_quote_price_check: Optional[bool] = None


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
        logger.debug("Creating TaprootWalletExtension instance")
        wallet = TaprootWalletExtension()

        # Get assets from tapd
        logger.debug("Calling wallet.list_assets()")
        assets_data = await wallet.list_assets()
        logger.debug(f"Retrieved {len(assets_data)} assets from tapd")

        # Return assets directly without storing in database
        logger.info(f"Successfully listed {len(assets_data)} assets for user {user.id}")
        return assets_data
    except Exception as e:
        logger.error(f"Failed to list assets: {str(e)}", exc_info=True)
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
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Create an invoice for a Taproot Asset."""
    logger.info(f"API: Creating invoice for asset_id={data.asset_id}, amount={data.amount}")
    try:
        logger.debug("API: Before creating wallet instance")
        # Create a wallet instance to communicate with tapd
        taproot_wallet = None
        try:
            taproot_wallet = TaprootWalletExtension()
            logger.debug("API: Successfully created TaprootWalletExtension instance")
        except Exception as e:
            logger.error(f"API ERROR: Failed to create TaprootWalletExtension: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize Taproot wallet: {str(e)}",
            )

        # Create the invoice using the TaprootWalletExtension
        logger.debug(f"API: Before calling create_invoice with asset_id={data.asset_id}, amount={data.amount}")
        invoice_response = None
        try:
            invoice_response = await taproot_wallet.create_invoice(
                amount=data.amount,
                memo=data.memo or "Taproot Asset Transfer",
                asset_id=data.asset_id,
                expiry=data.expiry,
            )
            logger.debug("API: After calling create_invoice")
            logger.debug(f"API: invoice_response type: {type(invoice_response)}")
            logger.debug(f"API: invoice_response: {invoice_response}")
        except Exception as e:
            logger.error(f"API ERROR: Failed in taproot_wallet.create_invoice: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice in wallet: {str(e)}",
            )

        if not invoice_response.ok:
            logger.error(f"API ERROR: Invoice creation failed: {invoice_response.error_message}")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice: {invoice_response.error_message}",
            )

        # Extract data from the invoice response
        logger.debug("API: Processing invoice_response")
        payment_hash = None
        payment_request = None
        buy_quote = None

        # Get payment_hash safely
        try:
            payment_hash = invoice_response.payment_hash
            logger.debug(f"API: Got payment_hash: {payment_hash}")
        except Exception as e:
            logger.error(f"API ERROR: Failed to get payment_hash: {str(e)}", exc_info=True)
            payment_hash = ""

        # Get payment_request safely
        try:
            payment_request = invoice_response.payment_request
            logger.debug(f"API: Got payment_request: {payment_request[:30] if payment_request else 'None'}...")
        except Exception as e:
            logger.error(f"API ERROR: Failed to get payment_request: {str(e)}", exc_info=True)
            payment_request = ""

        # Process extra field safely
        try:
            if hasattr(invoice_response, 'extra'):
                logger.debug(f"API: invoice_response has extra field, type: {type(invoice_response.extra)}")

                # Check if extra is a dictionary
                if invoice_response.extra is None:
                    logger.debug("API: extra is None, initializing empty dict")
                    invoice_response.extra = {}

                if not isinstance(invoice_response.extra, dict):
                    logger.warning(f"API: extra is not a dict! Converting from {type(invoice_response.extra)}")
                    # Convert to dictionary
                    if isinstance(invoice_response.extra, (list, tuple)):
                        invoice_response.extra = {"items": list(invoice_response.extra)}
                    else:
                        invoice_response.extra = {"value": str(invoice_response.extra)}

                # Now safely get buy_quote
                if "buy_quote" in invoice_response.extra:
                    buy_quote = invoice_response.extra.get("buy_quote")
                    logger.debug(f"API: Got buy_quote from extra, type: {type(buy_quote)}")

                    # Ensure buy_quote is a dictionary
                    if buy_quote is not None and not isinstance(buy_quote, dict):
                        logger.warning(f"API: buy_quote is not a dict! Converting from {type(buy_quote)}")
                        # Convert to dictionary
                        if isinstance(buy_quote, (list, tuple)):
                            buy_quote = {"items": list(buy_quote)}
                        else:
                            buy_quote = {"value": str(buy_quote)}
            else:
                logger.debug("API: invoice_response does not have extra field")
        except Exception as e:
            logger.error(f"API ERROR: Failed to process extra field: {str(e)}", exc_info=True)
            buy_quote = {}

        # Ensure buy_quote is a dict
        if buy_quote is None:
            buy_quote = {}

        logger.debug(f"API: Final extracted values - payment_hash: {payment_hash}, buy_quote type: {type(buy_quote)}")

        # Parse the original BOLT11 invoice to get the correct satoshi amount
        from lnbits import bolt11
        satoshi_amount = 0
        try:
            logger.debug("API: Decoding BOLT11 invoice")
            if payment_request:
                decoded_invoice = bolt11.decode(payment_request)
                satoshi_amount_msat = decoded_invoice.amount_msat
                satoshi_amount = satoshi_amount_msat // 1000 if satoshi_amount_msat is not None else 0
                logger.debug(f"API: Decoded invoice: satoshi_amount={satoshi_amount}")
            else:
                logger.warning("API: No payment_request to decode, using default amount")
                satoshi_amount = data.amount
        except Exception as e:
            logger.warning(f"API: Failed to decode BOLT11 invoice: {e}")
            satoshi_amount = data.amount  # Fallback to asset amount if decoding fails
            logger.debug(f"API: Using fallback satoshi_amount={satoshi_amount}")

        # Create an invoice record in the database
        logger.debug("API: Before creating invoice record in database")
        invoice = None
        try:
            # Last safety check for buy_quote
            if not isinstance(buy_quote, dict):
                logger.warning(f"API: Final check - buy_quote still not a dict! Converting from {type(buy_quote)}")
                buy_quote = {"value": str(buy_quote)}

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
                buy_quote=buy_quote,
            )
            logger.debug(f"API: Created invoice record with id={invoice.id}")
        except Exception as e:
            logger.error(f"API ERROR: Failed to create invoice record: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to store invoice in database: {str(e)}",
            )

        # Prepare final response
        logger.debug("API: Preparing final response")
        try:
            # Ensure accepted_buy_quote is a valid dict for response
            accepted_buy_quote = buy_quote if isinstance(buy_quote, dict) else {}

            response_data = {
                "payment_hash": payment_hash,
                "payment_request": payment_request,
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "satoshi_amount": satoshi_amount,
                "accepted_buy_quote": accepted_buy_quote,
                "checking_id": invoice.id if invoice else "",
            }
            logger.debug(f"API: Final response data prepared: {response_data}")
            logger.info(f"API: Successfully created invoice for asset_id={data.asset_id}")
            return response_data
        except Exception as e:
            logger.error(f"API ERROR: Failed to prepare response: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to format response: {str(e)}",
            )
    except Exception as e:
        # Get full traceback
        exc_type, exc_value, exc_traceback = sys.exc_info()
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)
        logger.error(f"API ERROR: Unhandled exception in api_create_invoice: {str(e)}")
        logger.error(f"API ERROR: Full traceback: {''.join(stack_trace)}")

        # Provide a user-friendly message for common errors
        detail = f"Failed to create Taproot Asset invoice: {str(e)}"
        if isinstance(e, grpc.RpcError) and "no asset channel balance found for asset" in str(e):
            detail = f"No channel balance found for asset {data.asset_id}. You need to create a channel with this asset first."

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=detail,
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
