"""
Payment service for Taproot Assets extension.
Handles payment-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
import re
import grpc
from http import HTTPStatus
from loguru import logger
import bolt11

from lnbits.core.models import WalletTypeInfo

from ..models import TaprootPaymentRequest, PaymentResponse, ParsedInvoice
from ..logging_utils import log_debug, log_info, log_warning, log_error, PAYMENT, API
from ..wallets.taproot_wallet import TaprootWalletExtension
from ..error_utils import log_error, handle_grpc_error, raise_http_exception
from ..crud import (
    get_invoice_by_payment_hash,
    is_internal_payment,
    is_self_payment,
    create_payment_record,
    record_asset_transaction,
    get_asset_balance
)
from ..notification_service import NotificationService


class PaymentService:
    """
    Service for handling Taproot Asset payments.
    This service encapsulates payment-related business logic.
    """
    
    @staticmethod
    async def parse_invoice(payment_request: str) -> ParsedInvoice:
        """
        Parse a BOLT11 payment request to extract invoice details.
        
        Args:
            payment_request: BOLT11 payment request to parse
            
        Returns:
            ParsedInvoice: Parsed invoice data
            
        Raises:
            Exception: If the invoice format is invalid
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
            
            # Create and return the parsed invoice
            return ParsedInvoice(
                payment_hash=decoded.payment_hash,
                amount=asset_amount,
                description=description,
                expiry=decoded.expiry if hasattr(decoded, "expiry") else 3600,
                timestamp=decoded.date,
                valid=True,
                asset_id=asset_id
            )
        except Exception as e:
            # Log the error with context
            log_error(e, context="Parsing invoice")
            raise Exception(f"Invalid invoice format: {str(e)}")
    
    @staticmethod
    async def determine_payment_type(
        payment_hash: str, 
        user_id: str
    ) -> str:
        """
        Determine the type of payment (external, internal, or self).
        
        Args:
            payment_hash: The payment hash to check
            user_id: The current user's ID
            
        Returns:
            str: Payment type - "external", "internal", or "self"
        """
        # Check if this is an internal payment
        is_internal_pay = await is_internal_payment(payment_hash)
        
        if is_internal_pay:
            # Check if this is a self-payment
            is_self_pay = await is_self_payment(payment_hash, user_id)
            return "self" if is_self_pay else "internal"
        
        return "external"
    
    @staticmethod
    async def process_external_payment(
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        parsed_invoice: ParsedInvoice
    ) -> PaymentResponse:
        """
        Process an external payment (to a different node).
        
        Args:
            data: The payment request data
            wallet: The wallet information
            parsed_invoice: The parsed invoice data
            
        Returns:
            PaymentResponse: The payment result
        """
        try:
            # Initialize wallet
            taproot_wallet = TaprootWalletExtension()
            
            # Set the user and wallet ID
            taproot_wallet.user = wallet.wallet.user
            taproot_wallet.id = wallet.wallet.id
            
            # Set fee limit
            from ..tapd_settings import taproot_settings
            fee_limit_sats = max(data.fee_limit_sats or taproot_settings.default_sat_fee, 10)
            
            # Make the payment
            payment = await taproot_wallet.pay_asset_invoice(
                invoice=data.payment_request,
                fee_limit_sats=fee_limit_sats,
                peer_pubkey=data.peer_pubkey,
                asset_id=parsed_invoice.asset_id
            )

            # Verify payment success
            if not payment.ok:
                raise Exception(f"Payment failed: {payment.error_message}")
                
            # Get payment details
            payment_hash = payment.checking_id
            preimage = payment.preimage or ""
            routing_fees_sats = payment.fee_msat // 1000 if payment.fee_msat else 0
            
            # Get asset details from extra
            asset_id = payment.extra.get("asset_id", parsed_invoice.asset_id or "")
            
            # Create descriptive memo
            memo = f"Taproot Asset Transfer"
            
            # Record the payment - for external Lightning payments only
            try:
                payment_record = await create_payment_record(
                    payment_hash=payment_hash,
                    payment_request=data.payment_request,
                    asset_id=asset_id,
                    asset_amount=parsed_invoice.amount,
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
                    amount=parsed_invoice.amount,
                    tx_type="debit",  # Outgoing payment
                    payment_hash=payment_hash,
                    fee=routing_fees_sats,
                    memo=memo
                )
                
                # Send notifications using the NotificationService
                if payment_record:
                    # Use the notification service to send all notifications in one go
                    await NotificationService.notify_transaction_complete(
                        user_id=wallet.wallet.user,
                        wallet_id=wallet.wallet.id,
                        payment_hash=payment_hash,
                        asset_id=asset_id,
                        asset_amount=parsed_invoice.amount,
                        tx_type="debit",  # Outgoing payment
                        memo=memo,
                        fee_sats=routing_fees_sats,
                        is_internal=False,
                        is_self_payment=False
                    )
                    
            except Exception as db_error:
                # Don't fail if payment record creation fails
                logger.error(f"Failed to store payment record: {str(db_error)}")
            
            # Return success response
            return PaymentResponse(
                success=True,
                payment_hash=payment_hash,
                preimage=preimage,
                fee_msat=payment.fee_msat or 0,
                sat_fee_paid=0,  # No service fee
                routing_fees_sats=routing_fees_sats,
                asset_amount=parsed_invoice.amount,
                asset_id=asset_id
            )
        
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
        except Exception as e:
            # Use the error utility with context
            log_error(e, context="Processing payment")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
                detail=f"Failed to pay Taproot Asset invoice: {str(e)}"
            )
    
    @staticmethod
    async def process_internal_payment(
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        parsed_invoice: ParsedInvoice
    ) -> PaymentResponse:
        """
        Process an internal payment (to another user on the same node).
        
        Args:
            data: The payment request data
            wallet: The wallet information
            parsed_invoice: The parsed invoice data
            
        Returns:
            PaymentResponse: The payment result
        """
        try:
            # Get the invoice to retrieve asset_id
            invoice = await get_invoice_by_payment_hash(parsed_invoice.payment_hash)
            if not invoice:
                raise_http_exception(
                    status_code=HTTPStatus.NOT_FOUND, 
                    detail="Invoice not found"
                )
                
            # Initialize wallet
            taproot_wallet = TaprootWalletExtension()
            
            # Set the user and wallet ID
            taproot_wallet.user = wallet.wallet.user
            taproot_wallet.id = wallet.wallet.id
            
            # Use the update_after_payment method for internal payments
            # This now handles all database operations internally
            result = await taproot_wallet.update_taproot_assets_after_payment(
                invoice=data.payment_request,
                payment_hash=parsed_invoice.payment_hash,
                fee_limit_sats=data.fee_limit_sats,
                asset_id=invoice.asset_id
            )
            
            if not result.ok:
                raise Exception(f"Internal payment failed: {result.error_message}")
            
            # Check if this is a self-payment
            is_self = await is_self_payment(parsed_invoice.payment_hash, wallet.wallet.user)
            
            # Return success response for internal payment
            return PaymentResponse(
                success=True,
                payment_hash=parsed_invoice.payment_hash,
                preimage=result.preimage or "",
                fee_msat=0,  # No routing fee for internal payment
                sat_fee_paid=0,
                routing_fees_sats=0,
                asset_amount=invoice.asset_amount,
                asset_id=invoice.asset_id,
                internal_payment=True,  # Flag to indicate this was an internal payment
                self_payment=is_self  # Flag to indicate if this was a self-payment
            )
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Internal payment error: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to process internal payment: {str(e)}"
            )
    
    @staticmethod
    async def process_payment(
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        force_payment_type: Optional[str] = None
    ) -> PaymentResponse:
        """
        Process a payment request, automatically determining the payment type
        unless a specific type is forced.
        
        Args:
            data: The payment request data
            wallet: The wallet information
            force_payment_type: Optional parameter to force a specific payment type
                           ("internal", "self", or "external")
        
        Returns:
            PaymentResponse: The payment result
        """
        # Parse the invoice to get payment details
        parsed_invoice = await PaymentService.parse_invoice(data.payment_request)
        
        # Determine the payment type if not forced
        if force_payment_type:
            payment_type = force_payment_type
            log_info(PAYMENT, f"Using forced payment type: {payment_type}")
        else:
            payment_type = await PaymentService.determine_payment_type(
                parsed_invoice.payment_hash, wallet.wallet.user
            )
            log_info(PAYMENT, f"Payment type determined: {payment_type}")
        
        # Process the payment based on its type
        if payment_type == "internal":
            return await PaymentService.process_internal_payment(data, wallet, parsed_invoice)
        elif payment_type == "self":
            return await PaymentService.process_self_payment(data, wallet, parsed_invoice)
        else:
            return await PaymentService.process_external_payment(data, wallet, parsed_invoice)
    
    @staticmethod
    async def process_self_payment(
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        parsed_invoice: ParsedInvoice
    ) -> PaymentResponse:
        """
        Process a self-payment (to the same user).
        
        Args:
            data: The payment request data
            wallet: The wallet information
            parsed_invoice: The parsed invoice data
            
        Returns:
            PaymentResponse: The payment result
        """
        try:
            # Get the invoice to retrieve asset_id
            invoice = await get_invoice_by_payment_hash(parsed_invoice.payment_hash)
            if not invoice:
                raise_http_exception(status_code=HTTPStatus.NOT_FOUND, detail="Invoice not found")

            # Initialize wallet
            taproot_wallet = TaprootWalletExtension()

            # Set the user and wallet ID
            taproot_wallet.user = wallet.wallet.user
            taproot_wallet.id = wallet.wallet.id

            # Use the update_after_payment method
            result = await taproot_wallet.update_taproot_assets_after_payment(
                invoice=data.payment_request,
                payment_hash=parsed_invoice.payment_hash,
                fee_limit_sats=data.fee_limit_sats,
                asset_id=invoice.asset_id
            )

            if not result.ok:
                raise Exception(f"Self-payment failed: {result.error_message}")

            # Send notifications using the NotificationService
            await NotificationService.notify_transaction_complete(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                payment_hash=parsed_invoice.payment_hash,
                asset_id=invoice.asset_id,
                asset_amount=invoice.asset_amount,
                tx_type="debit",  # Outgoing payment
                memo=invoice.memo or "Self-payment Taproot Asset Transfer",
                fee_sats=0,  # No fee for self-payments
                is_internal=True,
                is_self_payment=True
            )
            
            # Return success response
            return PaymentResponse(
                success=True,
                payment_hash=parsed_invoice.payment_hash,
                preimage=result.preimage or "",
                asset_amount=invoice.asset_amount,
                asset_id=invoice.asset_id,
                internal_payment=True,
                self_payment=True
            )
            
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Self-payment error: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to process self-payment: {str(e)}"
            )
