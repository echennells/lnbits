from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Query
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key
from pydantic import BaseModel

from .error_utils import raise_http_exception, handle_api_error
from .logging_utils import log_debug, log_info, log_warning, log_error, API
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
    log_debug(API, f"Getting settings for user {user.id}")
    return await SettingsService.get_settings(user)


@taproot_assets_api_router.put("/settings", status_code=HTTPStatus.OK)
@handle_api_error
async def api_update_settings(
    settings: TaprootSettings, user: User = Depends(check_user_exists)
):
    """Update Taproot Assets extension settings."""
    log_info(API, f"Updating settings for user {user.id}")
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
    log_info(API, f"Updating tapd settings for user {user.id}")
    return await SettingsService.update_tapd_settings(data.dict(exclude_unset=True), user)


@taproot_assets_api_router.get("/tapd-settings", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_tapd_settings(user: User = Depends(check_user_exists)):
    """Get Taproot daemon settings."""
    log_debug(API, f"Getting tapd settings for user {user.id}")
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
    log_debug(API, f"Parsing invoice for wallet {wallet.wallet.id}")
    parsed_invoice = await PaymentService.parse_invoice(payment_request)
    return parsed_invoice.dict()


@taproot_assets_api_router.get("/listassets", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_assets(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Assets for the current user with balance information."""
    log_debug(API, f"Listing assets for wallet {wallet.wallet.id}")
    return await AssetService.list_assets(wallet)


@taproot_assets_api_router.get("/assets/{asset_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset by ID with user balance."""
    log_debug(API, f"Getting asset {asset_id} for wallet {wallet.wallet.id}")
    return await AssetService.get_asset(asset_id, wallet)


@taproot_assets_api_router.post("/invoice", status_code=HTTPStatus.CREATED)
@handle_api_error
async def api_create_invoice(
    data: TaprootInvoiceRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Create an invoice for a Taproot Asset."""
    log_info(API, f"Creating invoice for asset {data.asset_id}, amount={data.amount}, wallet={wallet.wallet.id}")
    return await InvoiceService.create_invoice(data, wallet.wallet.user, wallet.wallet.id)


@taproot_assets_api_router.post("/pay", status_code=HTTPStatus.OK)
@handle_api_error
async def api_pay_invoice(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Pay a Taproot Asset invoice."""
    log_info(API, f"Processing payment request for wallet {wallet.wallet.id}")
    return await PaymentService.process_payment(data, wallet)


@taproot_assets_api_router.post("/internal-payment", status_code=HTTPStatus.OK)
@handle_api_error
async def api_internal_payment(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Process an internal payment for a Taproot Asset between different users on the same node."""
    log_info(API, f"Processing internal payment request for wallet {wallet.wallet.id}")
    
    # Parse the invoice to get payment details
    parsed_invoice = await PaymentService.parse_invoice(data.payment_request)
    
    # Verify this is actually an internal payment
    payment_type = await PaymentService.determine_payment_type(parsed_invoice.payment_hash, wallet.wallet.user)
    if payment_type not in ["internal", "self"]:
        log_warning(API, f"Not an internal payment. Invoice was not created on this node. Payment hash: {parsed_invoice.payment_hash}")
        raise_http_exception(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Not an internal payment. Invoice was not created on this node."
        )
    
    # Process as internal payment
    log_info(API, f"Confirmed as internal payment, processing")
    return await PaymentService.process_payment(data, wallet, force_payment_type="internal")


@taproot_assets_api_router.get("/payments", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_payments(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset payments for the current user."""
    log_debug(API, f"Listing payments for user {wallet.wallet.user}")
    return await PaymentRecordService.get_user_payments(wallet.wallet.user)


@taproot_assets_api_router.get("/fee-transactions", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_fee_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all fee transactions for the current user."""
    log_debug(API, f"Listing fee transactions for wallet {wallet.wallet.id}")
    return await PaymentRecordService.get_fee_transactions(wallet)


@taproot_assets_api_router.get("/invoices", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_invoices(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset invoices for the current user."""
    log_debug(API, f"Listing invoices for user {wallet.wallet.user}")
    return await InvoiceService.get_user_invoices(wallet.wallet.user)


@taproot_assets_api_router.get("/invoices/{invoice_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_invoice(
    invoice_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset invoice by ID."""
    log_debug(API, f"Getting invoice {invoice_id} for user {wallet.wallet.user}")
    return await InvoiceService.get_invoice(invoice_id, wallet.wallet.user)


@taproot_assets_api_router.put("/invoices/{invoice_id}/status", status_code=HTTPStatus.OK)
@handle_api_error
async def api_update_invoice_status(
    invoice_id: str,
    status: str = Query(..., description="New status for the invoice"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Update the status of a Taproot Asset invoice."""
    log_info(API, f"Updating invoice {invoice_id} status to {status} for user {wallet.wallet.user}")
    return await InvoiceService.update_invoice_status(invoice_id, status, wallet.wallet.user, wallet.wallet.id)


@taproot_assets_api_router.get("/asset-balances", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_balances(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get all asset balances for the current wallet."""
    log_debug(API, f"Getting asset balances for wallet {wallet.wallet.id}")
    return await AssetService.get_asset_balances(wallet)


@taproot_assets_api_router.get("/asset-balance/{asset_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_balance(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get the balance for a specific asset in the current wallet."""
    log_debug(API, f"Getting balance for asset {asset_id} in wallet {wallet.wallet.id}")
    return await AssetService.get_asset_balance(asset_id, wallet)


@taproot_assets_api_router.get("/asset-transactions", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
    asset_id: Optional[str] = None,
    limit: int = 100,
):
    """Get asset transactions for the current wallet."""
    log_debug(API, f"Getting asset transactions for wallet {wallet.wallet.id}, asset_id={asset_id or 'all'}, limit={limit}")
    return await AssetService.get_asset_transactions(wallet, asset_id, limit)
