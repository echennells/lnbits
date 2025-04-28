from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Query
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key
from loguru import logger
from pydantic import BaseModel

from .error_utils import raise_http_exception, handle_api_error
from .models import TaprootSettings, TaprootInvoiceRequest, TaprootPaymentRequest

# Import services
from .services.settings_service import SettingsService
from .services.asset_service import AssetService
from .services.invoice_service import InvoiceService
from .services.payment_service import PaymentService
from .services.payment_record_service import PaymentRecordService

# The parent router in __init__.py already adds the "/taproot_assets" prefix
# So we only need to add the API path here
taproot_assets_api_router = APIRouter(prefix="/api/v1/taproot", tags=["taproot_assets"])


@taproot_assets_api_router.get("/settings", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_settings(user: User = Depends(check_user_exists)):
    """Get Taproot Assets extension settings."""
    return await SettingsService.get_settings(user)


@taproot_assets_api_router.put("/settings", status_code=HTTPStatus.OK)
@handle_api_error
async def api_update_settings(
    settings: TaprootSettings, user: User = Depends(check_user_exists)
):
    """Update Taproot Assets extension settings."""
    return await SettingsService.update_settings(settings, user)


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
@handle_api_error
async def api_update_tapd_settings(
    data: TapdSettingsUpdate, user: User = Depends(check_user_exists)
):
    """Update Taproot daemon settings."""
    return await SettingsService.update_tapd_settings(data.dict(exclude_unset=True), user)


@taproot_assets_api_router.get("/tapd-settings", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_tapd_settings(user: User = Depends(check_user_exists)):
    """Get Taproot daemon settings."""
    return await SettingsService.get_tapd_settings(user)


@taproot_assets_api_router.get("/parse-invoice", status_code=HTTPStatus.OK)
@handle_api_error
async def api_parse_invoice(
    payment_request: str = Query(..., description="BOLT11 payment request to parse"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """
    Parse a BOLT11 payment request to extract invoice details for Taproot Assets.
    """
    parsed_invoice = await PaymentService.parse_invoice(payment_request)
    return parsed_invoice.dict()


@taproot_assets_api_router.get("/listassets", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_assets(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Assets for the current user with balance information."""
    return await AssetService.list_assets(wallet)


@taproot_assets_api_router.get("/assets/{asset_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset by ID with user balance."""
    return await AssetService.get_asset(asset_id, wallet)


@taproot_assets_api_router.post("/invoice", status_code=HTTPStatus.CREATED)
@handle_api_error
async def api_create_invoice(
    data: TaprootInvoiceRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Create an invoice for a Taproot Asset."""
    return await InvoiceService.create_invoice(data, wallet.wallet.user, wallet.wallet.id)


@taproot_assets_api_router.post("/pay", status_code=HTTPStatus.OK)
@handle_api_error
async def api_pay_invoice(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Pay a Taproot Asset invoice."""
    # First parse the invoice to get payment details
    parsed_invoice = await PaymentService.parse_invoice(data.payment_request)
    
    # Determine the payment type (external, internal, or self)
    payment_type = await PaymentService.determine_payment_type(parsed_invoice.payment_hash, wallet.wallet.user)
    
    # Process the payment based on its type
    if payment_type == "internal":
        return await PaymentService.process_internal_payment(data, wallet, parsed_invoice)
    elif payment_type == "self":
        return await PaymentService.process_self_payment(data, wallet, parsed_invoice)
    else:
        return await PaymentService.process_external_payment(data, wallet, parsed_invoice)


@taproot_assets_api_router.post("/internal-payment", status_code=HTTPStatus.OK)
@handle_api_error
async def api_internal_payment(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Process an internal payment for a Taproot Asset between different users on the same node."""
    # Parse the invoice to get payment details
    parsed_invoice = await PaymentService.parse_invoice(data.payment_request)
    
    # Verify this is actually an internal payment
    payment_type = await PaymentService.determine_payment_type(parsed_invoice.payment_hash, wallet.wallet.user)
    if payment_type not in ["internal", "self"]:
        raise_http_exception(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Not an internal payment. Invoice was not created on this node."
        )
    
    # Process as internal payment
    return await PaymentService.process_internal_payment(data, wallet, parsed_invoice)


# Keep self-payment endpoint for backward compatibility
@taproot_assets_api_router.post("/self-payment", status_code=HTTPStatus.OK)
@handle_api_error
async def api_self_payment(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Process a self-payment for a Taproot Asset (deprecated, use internal-payment instead)."""
    # Parse the invoice to get payment details
    parsed_invoice = await PaymentService.parse_invoice(data.payment_request)
    
    # Determine the payment type
    payment_type = await PaymentService.determine_payment_type(parsed_invoice.payment_hash, wallet.wallet.user)
    
    # Verify this is an internal payment
    if payment_type not in ["internal", "self"]:
        raise_http_exception(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Not an internal payment. Invoice was not created on this node."
        )
    
    # If it's a self-payment, process it as such
    if payment_type == "self":
        return await PaymentService.process_self_payment(data, wallet, parsed_invoice)
    
    # Otherwise, process as internal payment
    logger.info(f"Forwarding to internal payment since this is not a self-payment")
    return await PaymentService.process_internal_payment(data, wallet, parsed_invoice)



@taproot_assets_api_router.get("/payments", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_payments(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset payments for the current user."""
    return await PaymentRecordService.get_user_payments(wallet.wallet.user)


@taproot_assets_api_router.get("/fee-transactions", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_fee_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all fee transactions for the current user."""
    return await PaymentRecordService.get_fee_transactions(wallet)


@taproot_assets_api_router.get("/invoices", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_invoices(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset invoices for the current user."""
    return await InvoiceService.get_user_invoices(wallet.wallet.user)


@taproot_assets_api_router.get("/invoices/{invoice_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_invoice(
    invoice_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset invoice by ID."""
    return await InvoiceService.get_invoice(invoice_id, wallet.wallet.user)


@taproot_assets_api_router.put("/invoices/{invoice_id}/status", status_code=HTTPStatus.OK)
@handle_api_error
async def api_update_invoice_status(
    invoice_id: str,
    status: str = Query(..., description="New status for the invoice"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Update the status of a Taproot Asset invoice."""
    return await InvoiceService.update_invoice_status(invoice_id, status, wallet.wallet.user, wallet.wallet.id)


@taproot_assets_api_router.get("/asset-balances", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_balances(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get all asset balances for the current wallet."""
    return await AssetService.get_asset_balances(wallet)


@taproot_assets_api_router.get("/asset-balance/{asset_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_balance(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get the balance for a specific asset in the current wallet."""
    return await AssetService.get_asset_balance(asset_id, wallet)


@taproot_assets_api_router.get("/asset-transactions", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
    asset_id: Optional[str] = None,
    limit: int = 100,
):
    """Get asset transactions for the current wallet."""
    return await AssetService.get_asset_transactions(wallet, asset_id, limit)
