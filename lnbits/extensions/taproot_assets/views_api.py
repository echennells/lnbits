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
        # Fixed error handling to prevent the 'created_time' KeyError
        try:
            error_str = str(e)
            logger.error(f"Failed to list assets: {error_str}")
        except Exception as logging_error:
            logger.error(f"Error logging exception: {type(logging_error).__name__}")

        # Return an empty list instead of raising an exception
        return []


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
        # Create a wallet instance to communicate with tapd
        logger.debug("API: Before creating wallet instance")
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
        payment_hash = invoice_response.payment_hash
        payment_request = invoice_response.payment_request

        # Get satoshi fee from settings (for database record, not deduction)
        satoshi_amount = taproot_settings.default_sat_fee

        # Create an invoice record in the database
        logger.debug("API: Before creating invoice record in database")
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
            response_data = {
                "payment_hash": payment_hash,
                "payment_request": payment_request,
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "satoshi_amount": satoshi_amount,
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


@taproot_assets_api_router.post("/pay", status_code=HTTPStatus.OK)
async def api_pay_invoice(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Pay a Taproot Asset invoice."""
    logger.info(f"API: Paying invoice payment_request={data.payment_request[:30]}...")
    try:
        user_wallet = wallet.wallet
        taproot_wallet = TaprootWalletExtension()
        fee_limit_sats = taproot_settings.default_sat_fee  # Used as the fee limit for the payment

        # Decode the invoice to get the amount
        decoded_invoice = bolt11.decode(data.payment_request)
        invoice_amount_sats = int(decoded_invoice.amount_msat / 1000)

        # Check LNbits wallet balance for the invoice amount only (no additional fee)
        if user_wallet.balance_msat < invoice_amount_sats * 1000:
            raise HTTPException(
                status_code=HTTPStatus.PAYMENT_REQUIRED,
                detail=f"Insufficient balance to pay for this Taproot Asset transfer. You have {user_wallet.balance_msat/1000} sats, but need {invoice_amount_sats} sats."
            )

        # Deduct only the invoice amount from the LNbits wallet (pre-payment to litd)
        await update_wallet_balance(user_wallet, -invoice_amount_sats)
        logger.info(f"Deducted {invoice_amount_sats} sats from wallet {user_wallet.id}")
        await create_fee_transaction(
            user_id=user_wallet.user,
            wallet_id=user_wallet.id,
            asset_payment_hash=data.payment_request,
            fee_amount_msat=0,  # No additional service fee
            status="deducted"
        )

        # Pay the invoice using litd (tapd's LND node)
        try:
            payment = await taproot_wallet.pay_asset_invoice(
                invoice=data.payment_request,
                fee_limit_sats=fee_limit_sats
            )
            if not payment.ok:
                raise Exception(f"Payment failed: {payment.error_message}")
            logger.debug(f"Successfully paid invoice via litd: {payment.checking_id}")
        except Exception as e:
            # Refund the deducted amount if payment fails
            await update_wallet_balance(user_wallet, invoice_amount_sats)
            await create_fee_transaction(
                user_id=user_wallet.user,
                wallet_id=user_wallet.id,
                asset_payment_hash=data.payment_request,
                fee_amount_msat=0,
                status="refunded"
            )
            logger.error(f"Refunded {invoice_amount_sats} sats due to payment error")
            raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Failed to pay invoice: {str(e)}")

        # Deduct any additional routing fees from the LNbits wallet
        routing_fees_sats = payment.fee_msat // 1000 if payment.fee_msat else 0  # Convert msat to sat
        if routing_fees_sats > 0:
            await update_wallet_balance(user_wallet, -routing_fees_sats)
            logger.info(f"Deducted {routing_fees_sats} sats for routing fees from wallet {user_wallet.id}")

        # Prepare response
        response_data = {
            "success": True,
            "payment_hash": payment.checking_id,
            "preimage": payment.preimage or "",
            "fee_msat": payment.fee_msat or 0,
            "sat_fee_paid": 0,  # No additional service fee
            "routing_fees_sats": routing_fees_sats
        }
        logger.info(f"API: Successfully paid invoice, deducted {routing_fees_sats} sat routing fees")
        return response_data

    except Exception as e:
        # Handle any unhandled exceptions
        exc_type, exc_value, exc_traceback = sys.exc_info()
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)
        logger.error(f"API ERROR: Unhandled exception in api_pay_invoice: {str(e)}")
        logger.error(f"API ERROR: Full traceback: {''.join(stack_trace)}")

        # Don't catch HTTPExceptions - let them propagate with their status codes
        if isinstance(e, HTTPException):
            raise

        # Provide a user-friendly message for common errors
        detail = f"Failed to pay Taproot Asset invoice: {str(e)}"
        if isinstance(e, grpc.RpcError) and "no asset channel balance found for asset" in str(e):
            detail = "Insufficient channel balance for this asset."

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
