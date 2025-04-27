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

from .error_utils import handle_grpc_error, raise_http_exception, log_error, format_error_response

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
    get_user_payments,
    get_asset_balance,
    get_wallet_asset_balances,
    update_asset_balance,
    record_asset_transaction,
    get_asset_transactions,
    is_self_payment,
    is_internal_payment
)
from .models import TaprootSettings, TaprootAsset, TaprootInvoice, TaprootInvoiceRequest, TaprootPaymentRequest
from .wallets.taproot_wallet import TaprootWalletExtension
from .tapd_settings import taproot_settings
from .websocket import ws_manager
from .db import get_table_name

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


@taproot_assets_api_router.get("/parse-invoice", status_code=HTTPStatus.OK)
async def api_parse_invoice(
    payment_request: str = Query(..., description="BOLT11 payment request to parse"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """
    Parse a BOLT11 payment request to extract invoice details for Taproot Assets.
    """
    try:
        # Use the bolt11 library to decode the invoice
        decoded = bolt11.decode(payment_request)
        
        # Extract the description to look for asset information
        description = decoded.description if hasattr(decoded, "description") else ""
        
        # Initialize with default values
        asset_id = None
        asset_amount = 1  # Default to 1 for Taproot Asset invoices
        
        # Try to extract asset_id from description
        if description and 'asset_id=' in description:
            asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', description)
            if asset_id_match:
                asset_id = asset_id_match.group(1)
        
        # For Taproot Asset invoices, we need to ignore the Bitcoin amount
        # and use the asset amount from the description or default to 1
        if description:
            # Try to extract asset amount if present
            amount_match = re.search(r'amount=(\d+(\.\d+)?)', description) 
            if amount_match:
                asset_amount = float(amount_match.group(1))
        
        # Extract the relevant information
        result = {
            "payment_hash": decoded.payment_hash,
            "amount": asset_amount,  # Use the asset amount, not the Bitcoin amount
            "description": description,
            "expiry": decoded.expiry if hasattr(decoded, "expiry") else 3600,
            "timestamp": decoded.date,
            "valid": True,
            "asset_id": asset_id
        }
        
        logger.debug(f"Parsed invoice: {result}")
        return result
    except Exception as e:
        # Use the error utility with context
        log_error(e, context="Parsing invoice")
        raise_http_exception(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Invalid invoice format: {str(e)}"
        )


@taproot_assets_api_router.get("/listassets", status_code=HTTPStatus.OK)
async def api_list_assets(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Assets for the current user with balance information."""
    try:
        # Create a wallet instance to communicate with tapd
        taproot_wallet = TaprootWalletExtension()

        # Set the user and wallet ID
        taproot_wallet.user = wallet.wallet.user
        taproot_wallet.id = wallet.wallet.id

        # Get assets from tapd
        assets_data = await taproot_wallet.list_assets()
        
        # Get user information
        user = await get_user(wallet.wallet.user)
        if not user or not user.wallets:
            return []
        
        # Get user's wallet asset balances
        wallet_balances = {}
        for user_wallet in user.wallets:
            balances = await get_wallet_asset_balances(user_wallet.id)
            for balance in balances:
                wallet_balances[balance.asset_id] = balance.dict()
        
        # Enhance the assets data with user balance information
        for asset in assets_data:
            asset_id = asset.get("asset_id")
            if asset_id in wallet_balances:
                asset["user_balance"] = wallet_balances[asset_id]["balance"]
            else:
                asset["user_balance"] = 0
                
        # Send WebSocket notification with assets data
        if assets_data:
            await ws_manager.notify_assets_update(wallet.wallet.user, assets_data)
            
        return assets_data
    except Exception as e:
        logger.error(f"Failed to list assets: {str(e)}")
        return []  # Return empty list on error


@taproot_assets_api_router.get("/assets/{asset_id}", status_code=HTTPStatus.OK)
async def api_get_asset(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset by ID with user balance."""
    # Get user for permission check
    user = await get_user(wallet.wallet.user)
    if not user:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="User not found",
        )
        
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
    
    # Get user's balance for this asset
    balance = await get_asset_balance(wallet.wallet.id, asset.asset_id)
    
    # Add user balance to the response
    asset_dict = asset.dict()
    asset_dict["user_balance"] = balance.balance if balance else 0
    
    return asset_dict


@taproot_assets_api_router.post("/invoice", status_code=HTTPStatus.CREATED)
async def api_create_invoice(
    data: TaprootInvoiceRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Create an invoice for a Taproot Asset."""
    logger.info(f"Creating invoice for asset_id={data.asset_id}, amount={data.amount}")
    try:
        # Create a wallet instance
        taproot_wallet = TaprootWalletExtension()
        
        # Set the user and wallet ID
        taproot_wallet.user = wallet.wallet.user
        taproot_wallet.id = wallet.wallet.id
        
        # Create the invoice
        invoice_response = await taproot_wallet.create_invoice(
            amount=data.amount,
            memo=data.memo or "Taproot Asset Transfer",
            asset_id=data.asset_id,
            expiry=data.expiry,
            peer_pubkey=data.peer_pubkey,
        )

        if not invoice_response.ok:
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create invoice: {invoice_response.error_message}"
            )

        # Get satoshi fee from settings
        satoshi_amount = taproot_settings.default_sat_fee

        # Create invoice record
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

        # Send WebSocket notification for new invoice
        invoice_data = {
            "id": invoice.id,
            "payment_hash": invoice_response.payment_hash,
            "payment_request": invoice_response.payment_request,
            "asset_id": data.asset_id,
            "asset_amount": data.amount,
            "satoshi_amount": satoshi_amount,
            "memo": invoice.memo,
            "status": "pending",
            "created_at": invoice.created_at.isoformat() if hasattr(invoice.created_at, "isoformat") else str(invoice.created_at)
        }
        
        # Use WebSocket notification with error handling
        notification_sent = await ws_manager.notify_invoice_update(wallet.wallet.user, invoice_data)
        if not notification_sent:
            logger.warning(f"Failed to send WebSocket notification for invoice {invoice.id}")

        # Return response
        return {
            "payment_hash": invoice_response.payment_hash,
            "payment_request": invoice_response.payment_request,
            "asset_id": data.asset_id,
            "asset_amount": data.amount,
            "satoshi_amount": satoshi_amount,
            "checking_id": invoice.id,
        }
        
    except grpc.aio.AioRpcError as e:
        # Use standardized gRPC error handling
        context = f"Creating invoice for asset {data.asset_id}"
        error_message, status_code = handle_grpc_error(e, context)
        raise_http_exception(status_code, error_message)
    except HTTPException:
        # Don't re-wrap HTTPExceptions
        raise
    except Exception as e:
        # Log error with context and raise standard exception
        log_error(e, context=f"Creating invoice for asset {data.asset_id}")
        raise_http_exception(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Taproot Asset invoice: {str(e)}"
        )


@taproot_assets_api_router.post("/pay", status_code=HTTPStatus.OK)
async def api_pay_invoice(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Pay a Taproot Asset invoice."""
    try:
        # Get the parsed invoice first to determine the correct asset amount
        try:
            parsed_invoice = await api_parse_invoice(data.payment_request, wallet)
            payment_hash = parsed_invoice.get("payment_hash")
            asset_amount = parsed_invoice.get("amount", 1)  # Default to 1 if not found
            logger.info(f"Parsed invoice amount: {asset_amount}")
        except Exception as parse_error:
            logger.error(f"Error parsing invoice (using default amount): {str(parse_error)}")
            asset_amount = 1  # Default to 1 if parsing fails
            payment_hash = None
            
        # If we couldn't get the payment hash from parsing, try harder
        if not payment_hash:
            try:
                # Use the bolt11 library directly
                decoded = bolt11.decode(data.payment_request)
                payment_hash = decoded.payment_hash
            except Exception as e:
                logger.error(f"Failed to extract payment hash from invoice: {str(e)}")
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Could not extract payment hash from invoice"
                )
        
        # Check if this is an internal payment
        is_internal = await is_internal_payment(payment_hash)
        logger.info(f"Internal payment detection for {payment_hash}: {is_internal}")
        
        # Check if this is a self-payment
        is_self = await is_self_payment(payment_hash, wallet.wallet.user)
        logger.info(f"Self-payment detection for {payment_hash}: {is_self}")
        
        # Initialize wallet
        taproot_wallet = TaprootWalletExtension()
        
        # Set the user and wallet ID
        taproot_wallet.user = wallet.wallet.user
        taproot_wallet.id = wallet.wallet.id
        
        # If this is an internal payment, handle it with database updates
        if is_internal:
            logger.info(f"Handling internal payment for invoice with hash: {payment_hash}")
            
            # Get the invoice to retrieve asset_id
            invoice = await get_invoice_by_payment_hash(payment_hash)
            if not invoice:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND, 
                    detail="Invoice not found"
                )
                
            # Use the update_after_payment method for internal payments
            # This now handles all database operations internally
            result = await taproot_wallet.update_taproot_assets_after_payment(
                invoice=data.payment_request,
                payment_hash=payment_hash,
                fee_limit_sats=data.fee_limit_sats,
                asset_id=invoice.asset_id
            )
            
            if not result.ok:
                raise Exception(f"Internal payment failed: {result.error_message}")
            
            # Return success response for internal payment
            return {
                "success": True,
                "payment_hash": payment_hash,
                "preimage": result.preimage or "",
                "fee_msat": 0,  # No routing fee for internal payment
                "sat_fee_paid": 0,
                "routing_fees_sats": 0,
                "asset_amount": invoice.asset_amount,
                "asset_id": invoice.asset_id,
                "internal_payment": True,  # Flag to indicate this was an internal payment
                "self_payment": is_self  # Flag to indicate if this was a self-payment
            }

        # If not a self-payment or internal payment, proceed with normal payment flow
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
            
        # Get payment details
        payment_hash = payment.checking_id
        preimage = payment.preimage or ""
        routing_fees_sats = payment.fee_msat // 1000 if payment.fee_msat else 0
        
        # Get asset details from extra
        asset_id = payment.extra.get("asset_id", "")
        
        # Use the parsed amount instead of what's in the payment response
        # This is important for Taproot Asset invoices
        
        # Create descriptive memo
        memo = f"Taproot Asset Transfer"
        
        # Record the payment - for external Lightning payments only
        try:
            payment_record = await create_payment_record(
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
            
            # Record asset transaction and update balance for external payments
            await record_asset_transaction(
                wallet_id=wallet.wallet.id,
                asset_id=asset_id,
                amount=asset_amount,
                tx_type="debit",  # Outgoing payment
                payment_hash=payment_hash,
                fee=routing_fees_sats,
                memo=memo
            )
            
            # Send WebSocket notification of payment
            if payment_record:
                payment_data = {
                    "id": payment_record.id,
                    "payment_hash": payment_hash,
                    "asset_id": asset_id,
                    "asset_amount": asset_amount,
                    "fee_sats": routing_fees_sats,
                    "memo": memo,
                    "status": "completed",
                    "created_at": payment_record.created_at.isoformat() if hasattr(payment_record.created_at, "isoformat") else str(payment_record.created_at)
                }
                await ws_manager.notify_payment_update(wallet.wallet.user, payment_data)
                
                # Also update asset balances via WebSocket
                try:
                    taproot_wallet = TaprootWalletExtension()  # Create a fresh instance
                    taproot_wallet.user = wallet.wallet.user
                    taproot_wallet.id = wallet.wallet.id
                    
                    assets = await taproot_wallet.list_assets()
                    filtered_assets = [asset for asset in assets if asset.get("channel_info")]
                    
                    # Add user balance information
                    for asset in filtered_assets:
                        asset_id = asset.get("asset_id")
                        balance = await get_asset_balance(wallet.wallet.id, asset_id)
                        asset["user_balance"] = balance.balance if balance else 0
                        
                    if filtered_assets:
                        await ws_manager.notify_assets_update(wallet.wallet.user, filtered_assets)
                except Exception as asset_err:
                    logger.error(f"Failed to update assets after payment: {str(asset_err)}")
                
        except Exception as db_error:
            # Don't fail if payment record creation fails
            logger.error(f"Failed to store payment record: {str(db_error)}")
        
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
    
    except grpc.aio.AioRpcError as e:
        # Use standardized gRPC error handling
        context = "Processing payment"
        error_message, status_code = handle_grpc_error(e, context)
        
        # Handle special case for self-payment detection
        if "self-payments not allowed" in e.details().lower():
            # Log that our detection failed
            logger.warning(f"Self-payment detection failed for an invoice with error: {e.details()}")
            
            # Try to extract payment hash from error message for debugging
            match = re.search(r'hash=([a-fA-F0-9]{64})', e.details())
            if match:
                logger.warning(f"Potentially missed internal payment for hash: {match.group(1)}")
            
            # Use more specific error message
            error_message = "This invoice belongs to another user on this node. The system will handle this as an internal payment automatically."
        
        # Raise the HTTP exception with the standardized error message
        raise_http_exception(status_code, error_message)
    except HTTPException:
        # Let HTTP exceptions propagate
        raise
    except Exception as e:
        # Use the error utility with context
        log_error(e, context="Processing payment")
        raise_http_exception(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
            detail=f"Failed to pay Taproot Asset invoice: {str(e)}"
        )


@taproot_assets_api_router.post("/internal-payment", status_code=HTTPStatus.OK)
async def api_internal_payment(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Process an internal payment for a Taproot Asset between different users on the same node."""
    try:
        # Parse the invoice to get payment hash
        try:
            parsed_invoice = await api_parse_invoice(data.payment_request, wallet)
            payment_hash = parsed_invoice.get("payment_hash")
        except Exception as e:
            logger.error(f"Failed to parse invoice: {str(e)}")

            # Try direct extraction as fallback
            try:
                decoded = bolt11.decode(data.payment_request)
                payment_hash = decoded.payment_hash
            except Exception as e2:
                logger.error(f"Failed to extract payment hash: {str(e2)}")
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Could not extract payment hash from invoice"
                )

        # Verify this is actually an internal payment
        is_internal = await is_internal_payment(payment_hash)
        if not is_internal:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Not an internal payment. Invoice was not created on this node."
            )

        # Get the invoice to retrieve asset_id
        invoice = await get_invoice_by_payment_hash(payment_hash)
        if not invoice:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Invoice not found")

        # Initialize wallet
        taproot_wallet = TaprootWalletExtension()

        # Set the user and wallet ID
        taproot_wallet.user = wallet.wallet.user
        taproot_wallet.id = wallet.wallet.id

        # Use the update_after_payment method which now handles all database operations internally
        result = await taproot_wallet.update_taproot_assets_after_payment(
            invoice=data.payment_request,
            payment_hash=payment_hash,
            fee_limit_sats=data.fee_limit_sats,
            asset_id=invoice.asset_id
        )

        if not result.ok:
            raise Exception(f"Internal payment failed: {result.error_message}")

        # Return success response
        return {
            "success": True,
            "payment_hash": payment_hash,
            "preimage": result.preimage or "",
            "asset_amount": invoice.asset_amount,
            "asset_id": invoice.asset_id,
            "internal_payment": True,
            "self_payment": await is_self_payment(payment_hash, wallet.wallet.user)
        }

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Internal payment error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to process internal payment: {str(e)}"
        )


# Keep self-payment endpoint for backward compatibility
@taproot_assets_api_router.post("/self-payment", status_code=HTTPStatus.OK)
async def api_self_payment(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Process a self-payment for a Taproot Asset (deprecated, use internal-payment instead)."""
    try:
        # Parse the invoice to get payment hash
        try:
            parsed_invoice = await api_parse_invoice(data.payment_request, wallet)
            payment_hash = parsed_invoice.get("payment_hash")
        except Exception as e:
            logger.error(f"Failed to parse invoice: {str(e)}")

            # Try direct extraction as fallback
            try:
                decoded = bolt11.decode(data.payment_request)
                payment_hash = decoded.payment_hash
            except Exception as e2:
                logger.error(f"Failed to extract payment hash: {str(e2)}")
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Could not extract payment hash from invoice"
                )

        # Check if this is an internal payment
        is_internal = await is_internal_payment(payment_hash)
        if not is_internal:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Not an internal payment. Invoice was not created on this node."
            )

        # Get the invoice to retrieve asset_id
        invoice = await get_invoice_by_payment_hash(payment_hash)
        if not invoice:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Invoice not found")

        # Check if this is a true self-payment (same user)
        is_self = await is_self_payment(payment_hash, wallet.wallet.user)
        if not is_self:
            # Rather than failing, forward to internal payment endpoint
            logger.info(f"Forwarding to internal payment since this is not a self-payment")
            return await api_internal_payment(data, wallet)

        # Initialize wallet
        taproot_wallet = TaprootWalletExtension()

        # Set the user and wallet ID
        taproot_wallet.user = wallet.wallet.user
        taproot_wallet.id = wallet.wallet.id

        # Use the update_after_payment method
        result = await taproot_wallet.update_taproot_assets_after_payment(
            invoice=data.payment_request,
            payment_hash=payment_hash,
            fee_limit_sats=data.fee_limit_sats,
            asset_id=invoice.asset_id
        )

        if not result.ok:
            raise Exception(f"Self-payment failed: {result.error_message}")

        # Return success response
        return {
            "success": True,
            "payment_hash": payment_hash,
            "preimage": result.preimage or "",
            "asset_amount": invoice.asset_amount,
            "asset_id": invoice.asset_id,
            "self_payment": True
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Self-payment error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to process self-payment: {str(e)}"
        )


@taproot_assets_api_router.get("/payments", status_code=HTTPStatus.OK)
async def api_list_payments(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset payments for the current user."""
    try:
        payments = await get_user_payments(wallet.wallet.user)
        return payments
    except Exception as e:
        logger.error(f"Error retrieving payments: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve payments: {str(e)}",
        )


@taproot_assets_api_router.get("/fee-transactions", status_code=HTTPStatus.OK)
async def api_list_fee_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all fee transactions for the current user."""
    # Get user information
    user = await get_user(wallet.wallet.user)
    if not user:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="User not found",
        )
        
    # If admin, can view all transactions, otherwise just their own
    if user.admin:
        transactions = await get_fee_transactions()
    else:
        transactions = await get_fee_transactions(user.id)

    return transactions


@taproot_assets_api_router.get("/invoices", status_code=HTTPStatus.OK)
async def api_list_invoices(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset invoices for the current user."""
    try:
        invoices = await get_user_invoices(wallet.wallet.user)
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
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset invoice by ID."""
    invoice = await get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Invoice not found",
        )

    if invoice.user_id != wallet.wallet.user:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Not your invoice",
        )

    return invoice


@taproot_assets_api_router.put("/invoices/{invoice_id}/status", status_code=HTTPStatus.OK)
async def api_update_invoice_status(
    invoice_id: str,
    status: str = Query(..., description="New status for the invoice"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Update the status of a Taproot Asset invoice."""
    invoice = await get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Invoice not found",
        )

    if invoice.user_id != wallet.wallet.user:
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
    
    # If marking as paid, update the asset balance
    if status == "paid" and updated_invoice:
        try:
            # Record the transaction and update balance
            await record_asset_transaction(
                wallet_id=invoice.wallet_id,
                asset_id=invoice.asset_id,
                amount=invoice.asset_amount,
                tx_type="credit",  # Incoming payment
                payment_hash=invoice.payment_hash,
                memo=invoice.memo or f"Received {invoice.asset_amount} of asset {invoice.asset_id}"
            )
        except Exception as e:
            logger.error(f"Failed to update asset balance: {str(e)}")
    
    # Send WebSocket notification about status update
    if updated_invoice:
        invoice_data = {
            "id": updated_invoice.id,
            "payment_hash": updated_invoice.payment_hash,
            "status": updated_invoice.status,
            "asset_id": updated_invoice.asset_id,
            "asset_amount": updated_invoice.asset_amount
        }
        await ws_manager.notify_invoice_update(wallet.wallet.user, invoice_data)
    
    return updated_invoice


@taproot_assets_api_router.get("/asset-balances", status_code=HTTPStatus.OK)
async def api_get_asset_balances(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get all asset balances for the current wallet."""
    try:
        balances = await get_wallet_asset_balances(wallet.wallet.id)
        return balances
    except Exception as e:
        logger.error(f"Error retrieving asset balances: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve asset balances: {str(e)}",
        )


@taproot_assets_api_router.get("/asset-balance/{asset_id}", status_code=HTTPStatus.OK)
async def api_get_asset_balance(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get the balance for a specific asset in the current wallet."""
    try:
        balance = await get_asset_balance(wallet.wallet.id, asset_id)
        if not balance:
            return {"wallet_id": wallet.wallet.id, "asset_id": asset_id, "balance": 0}
        return balance
    except Exception as e:
        logger.error(f"Error retrieving asset balance: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve asset balance: {str(e)}",
        )


@taproot_assets_api_router.get("/asset-transactions", status_code=HTTPStatus.OK)
async def api_get_asset_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
    asset_id: Optional[str] = None,
    limit: int = 100,
):
    """Get asset transactions for the current wallet."""
    try:
        transactions = await get_asset_transactions(wallet.wallet.id, asset_id, limit)
        return transactions
    except Exception as e:
        logger.error(f"Error retrieving asset transactions: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve asset transactions: {str(e)}",
        )
