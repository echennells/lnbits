"""
Invoice service for Taproot Assets extension.
Handles invoice-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
from http import HTTPStatus
from loguru import logger

from lnbits.core.models import WalletTypeInfo, User

from ..models import TaprootInvoiceRequest, InvoiceResponse, TaprootInvoice
from ..wallets.taproot_factory import TaprootAssetsFactory
from ..error_utils import log_error, handle_grpc_error, raise_http_exception
from ..logging_utils import API
from ..crud import (
    create_invoice,
    get_invoice,
    get_invoice_by_payment_hash,
    get_user_invoices,
    update_invoice_status,
    record_asset_transaction
)
from ..notification_service import NotificationService
from ..tapd_settings import taproot_settings


class InvoiceService:
    """
    Service for handling Taproot Asset invoices.
    This service encapsulates invoice-related business logic.
    """
    
    @staticmethod
    async def create_invoice(
        data: TaprootInvoiceRequest,
        user_id: str,
        wallet_id: str
    ) -> InvoiceResponse:
        """
        Create an invoice for a Taproot Asset.
        
        Args:
            data: The invoice request data
            user_id: The user ID
            wallet_id: The wallet ID
            
        Returns:
            InvoiceResponse: The created invoice
            
        Raises:
            HTTPException: If invoice creation fails
        """
        logger.info(f"Creating invoice for asset_id={data.asset_id}, amount={data.amount}")
        try:
            # Create a wallet instance using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=user_id,
                wallet_id=wallet_id
            )
            
            # Create the invoice
            invoice_response = await taproot_wallet.create_invoice(
                amount=data.amount,
                memo=data.memo or "",
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

            # Map the BaseInvoiceResponse to our expected fields
            payment_hash = invoice_response.checking_id
            payment_request = invoice_response.payment_request
            
            # Create invoice record
            invoice = await create_invoice(
                asset_id=data.asset_id,
                asset_amount=data.amount,
                satoshi_amount=satoshi_amount,
                payment_hash=payment_hash,
                payment_request=payment_request,
                user_id=user_id,
                wallet_id=wallet_id,
                memo=data.memo or "",
                expiry=data.expiry,
            )

            # Send WebSocket notification for new invoice
            invoice_data = {
                "id": invoice.id,
                "payment_hash": payment_hash,
                "payment_request": payment_request,
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "satoshi_amount": satoshi_amount,
                "memo": invoice.memo,
                "status": "pending",
                "created_at": invoice.created_at.isoformat() if hasattr(invoice.created_at, "isoformat") else str(invoice.created_at)
            }
            
            # Use NotificationService for WebSocket notification
            notification_sent = await NotificationService.notify_invoice_update(user_id, invoice_data)
            if not notification_sent:
                logger.warning(f"Failed to send WebSocket notification for invoice {invoice.id}")

            # Return response
            return InvoiceResponse(
                payment_hash=payment_hash,
                payment_request=payment_request,
                asset_id=data.asset_id,
                asset_amount=data.amount,
                satoshi_amount=satoshi_amount,
                checking_id=invoice.id,
            )
            
        except Exception as e:
            # Log error with context and raise standard exception
            log_error(API, f"Error creating invoice for asset {data.asset_id}: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to create Taproot Asset invoice: {str(e)}"
            )
    
    @staticmethod
    async def get_invoice(invoice_id: str, user_id: str) -> TaprootInvoice:
        """
        Get a specific Taproot Asset invoice by ID.
        
        Args:
            invoice_id: The invoice ID
            user_id: The user ID
            
        Returns:
            TaprootInvoice: The invoice
            
        Raises:
            HTTPException: If the invoice is not found or doesn't belong to the user
        """
        invoice = await get_invoice(invoice_id)

        if not invoice:
            raise_http_exception(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Invoice not found",
            )

        if invoice.user_id != user_id:
            raise_http_exception(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Not your invoice",
            )

        return invoice
    
    @staticmethod
    async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
        """
        Get all Taproot Asset invoices for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            List[TaprootInvoice]: List of invoices
            
        Raises:
            HTTPException: If there's an error retrieving invoices
        """
        try:
            invoices = await get_user_invoices(user_id)
            return invoices
        except Exception as e:
            logger.error(f"Error retrieving invoices: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve invoices: {str(e)}",
            )
    
    @staticmethod
    async def update_invoice_status(
        invoice_id: str,
        status: str,
        user_id: str,
        wallet_id: str
    ) -> TaprootInvoice:
        """
        Update the status of a Taproot Asset invoice.
        
        Args:
            invoice_id: The invoice ID
            status: The new status
            user_id: The user ID
            wallet_id: The wallet ID
            
        Returns:
            TaprootInvoice: The updated invoice
            
        Raises:
            HTTPException: If the invoice is not found, doesn't belong to the user, or the status is invalid
        """
        invoice = await get_invoice(invoice_id)

        if not invoice:
            raise_http_exception(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Invoice not found",
            )

        if invoice.user_id != user_id:
            raise_http_exception(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Not your invoice",
            )

        if status not in ["pending", "paid", "expired", "cancelled"]:
            raise_http_exception(
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
                    memo=invoice.memo
                )
            except Exception as e:
                logger.error(f"Failed to update asset balance: {str(e)}")
        
        # Send WebSocket notification about status update using NotificationService
        if updated_invoice:
            invoice_data = {
                "id": updated_invoice.id,
                "payment_hash": updated_invoice.payment_hash,
                "status": updated_invoice.status,
                "asset_id": updated_invoice.asset_id,
                "asset_amount": updated_invoice.asset_amount
            }
            await NotificationService.notify_invoice_update(user_id, invoice_data)
        
        return updated_invoice
