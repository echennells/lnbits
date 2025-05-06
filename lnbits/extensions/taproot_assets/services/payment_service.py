"""
Payment service for Taproot Assets extension.
Handles payment-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
import re
import grpc
from http import HTTPStatus
from fastapi import HTTPException
from loguru import logger
import bolt11

from lnbits.core.models import WalletTypeInfo

from ..models import TaprootPaymentRequest, PaymentResponse, ParsedInvoice
from ..logging_utils import log_debug, log_info, log_warning, log_error, PAYMENT, API
from ..wallets.taproot_factory import TaprootAssetsFactory
from ..error_utils import log_error, handle_grpc_error, raise_http_exception, ErrorContext
from ..crud import (
    get_invoice_by_payment_hash,
    is_internal_payment,
    is_self_payment
)
from ..settlement_service import SettlementService


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
        with ErrorContext("parse_invoice", API):
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
        with ErrorContext("process_external_payment", PAYMENT):
            # Initialize wallet using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )
            
            # Set fee limit
            from ..tapd_settings import taproot_settings
            fee_limit_sats = max(data.fee_limit_sats or taproot_settings.default_sat_fee, 10)
            
            # Make the payment
            # Pass the asset_id from the parsed invoice to the pay_asset_invoice method
            # This is important because the pay_asset_invoice method will use this asset_id
            # to pay the invoice with the correct asset
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
            
            # Get asset_id from the node's cache if available, otherwise use the parsed invoice
            asset_id = ""
            if taproot_wallet.node:
                cached_asset_id = taproot_wallet.node._get_asset_id(payment_hash)
                if cached_asset_id:
                    asset_id = cached_asset_id
                    log_info(PAYMENT, f"Using asset_id from cache: {asset_id}")
            
            # If no cached asset_id, use the one from the parsed invoice
            if not asset_id:
                asset_id = parsed_invoice.asset_id or ""
                log_info(PAYMENT, f"Using asset_id from parsed invoice: {asset_id}")
            
            # Extract memo from the invoice description if available
            memo = parsed_invoice.description if parsed_invoice.description else None
            
            # Use the centralized SettlementService to record the payment
            # IMPORTANT: Make sure to use the correct asset amount (parsed_invoice.amount) and not the fee_limit
            payment_success, payment_record = await SettlementService.record_payment(
                payment_hash=payment_hash,
                payment_request=data.payment_request,
                asset_id=asset_id,
                asset_amount=parsed_invoice.amount,  # Use the correct asset amount from the invoice
                fee_sats=routing_fees_sats,         # Use the actual fee paid, not the limit
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                memo=memo,
                preimage=preimage,
                is_internal=False,
                is_self_payment=False
            )
            
            if not payment_success:
                log_warning(PAYMENT, "Payment was successful but failed to record in database")
            
            # Return success response
            return PaymentResponse(
                success=True,
                payment_hash=payment_hash,
                preimage=preimage,
                fee_msat=payment.fee_msat or 0,
                sat_fee_paid=0,  # No service fee
                routing_fees_sats=routing_fees_sats,
                asset_amount=parsed_invoice.amount,  # Use the correct asset amount from the invoice
                asset_id=asset_id,
                memo=memo
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
        with ErrorContext("process_internal_payment", PAYMENT):
            # Get the invoice to retrieve asset_id
            invoice = await get_invoice_by_payment_hash(parsed_invoice.payment_hash)
            if not invoice:
                raise_http_exception(
                    status_code=HTTPStatus.NOT_FOUND, 
                    detail="Invoice not found"
                )
                
            # Initialize wallet using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )
            
            # Check if this is a self-payment
            is_self = await is_self_payment(parsed_invoice.payment_hash, wallet.wallet.user)
            
            # First use SettlementService to settle the invoice
            success, settlement_result = await SettlementService.settle_invoice(
                payment_hash=parsed_invoice.payment_hash,
                node=taproot_wallet.node,
                is_internal=True,
                is_self_payment=is_self,
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )
            
            if not success:
                raise Exception(f"Failed to settle internal payment: {settlement_result.get('error', 'Unknown error')}")
            
            # Then use SettlementService to record the payment
            payment_success, payment_record = await SettlementService.record_payment(
                payment_hash=parsed_invoice.payment_hash,
                payment_request=data.payment_request,
                asset_id=invoice.asset_id,
                asset_amount=invoice.asset_amount,  # Use the actual asset amount from the invoice
                fee_sats=0,  # No fee for internal payments
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                memo=invoice.memo or "",
                preimage=settlement_result.get('preimage', ''),
                is_internal=True,
                is_self_payment=is_self
            )
            
            if not payment_success:
                log_warning(PAYMENT, "Internal payment was successful but failed to record in database")
            
            # Return success response for internal payment
            return PaymentResponse(
                success=True,
                payment_hash=parsed_invoice.payment_hash,
                preimage=settlement_result.get('preimage', ''),
                fee_msat=0,  # No routing fee for internal payment
                sat_fee_paid=0,
                routing_fees_sats=0,
                asset_amount=invoice.asset_amount,
                asset_id=invoice.asset_id,
                memo=invoice.memo,
                internal_payment=True,  # Flag to indicate this was an internal payment
                self_payment=is_self  # Flag to indicate if this was a self-payment
            )
    
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
        with ErrorContext("process_self_payment", PAYMENT):
            # Get the invoice to retrieve asset_id
            invoice = await get_invoice_by_payment_hash(parsed_invoice.payment_hash)
            if not invoice:
                raise_http_exception(status_code=HTTPStatus.NOT_FOUND, detail="Invoice not found")

            # Initialize wallet using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )

            # Use SettlementService to settle the invoice
            success, settlement_result = await SettlementService.settle_invoice(
                payment_hash=parsed_invoice.payment_hash,
                node=taproot_wallet.node,
                is_internal=True,
                is_self_payment=True,
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )
            
            if not success:
                raise Exception(f"Failed to settle self-payment: {settlement_result.get('error', 'Unknown error')}")

            # Then use SettlementService to record the payment
            payment_success, payment_record = await SettlementService.record_payment(
                payment_hash=parsed_invoice.payment_hash,
                payment_request=data.payment_request,
                asset_id=invoice.asset_id,
                asset_amount=invoice.asset_amount,  # Use the actual asset amount from the invoice
                fee_sats=0,  # No fee for self-payments
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                memo=invoice.memo or "",
                preimage=settlement_result.get('preimage', ''),
                is_internal=True,
                is_self_payment=True
            )
            
            if not payment_success:
                log_warning(PAYMENT, "Self-payment was successful but failed to record in database")
            
            # Return success response
            return PaymentResponse(
                success=True,
                payment_hash=parsed_invoice.payment_hash,
                preimage=settlement_result.get('preimage', ''),
                asset_amount=invoice.asset_amount,
                asset_id=invoice.asset_id,
                memo=invoice.memo,
                internal_payment=True,
                self_payment=True
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
                           ("internal" or "external")
        
        Returns:
            PaymentResponse: The payment result
        """
        with ErrorContext("process_payment", PAYMENT):
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
            
            # Reject self-payments
            if payment_type == "self":
                log_warning(PAYMENT, f"Self-payment rejected for payment hash: {parsed_invoice.payment_hash}")
                raise Exception("Self-payments are not allowed. You cannot pay your own invoice.")
            
            # Process the payment based on its type
            if payment_type == "internal":
                return await PaymentService.process_internal_payment(data, wallet, parsed_invoice)
            else:
                return await PaymentService.process_external_payment(data, wallet, parsed_invoice)
