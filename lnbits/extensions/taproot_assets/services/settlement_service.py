"""
Centralized Settlement Service for Taproot Assets extension.
Handles all invoice settlement logic consistently across different payment types.
"""
import asyncio
import hashlib
import time
from typing import Optional, Dict, Any, Tuple, List, Protocol, Type
import grpc
import grpc.aio
from abc import ABC, abstractmethod
from loguru import logger

from ..tapd.taproot_adapter import invoices_pb2
from .notification_service import NotificationService
from ..models import TaprootInvoice, TaprootPayment
from ..db_utils import transaction, with_transaction

# Import database functions from crud re-exports
from ..crud import (
    get_invoice_by_payment_hash,
    update_invoice_status,
    is_internal_payment,
    is_self_payment,
    record_asset_transaction,
    get_asset_balance,
    create_payment_record
)

from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, PAYMENT, TRANSFER, LogContext
)
from ..error_utils import ErrorContext, handle_error
from ..asset_utils import resolve_asset_id

# Define a settlement strategy abstract base class
class SettlementStrategy(ABC):
    """Base class for settlement strategies."""
    
    @abstractmethod
    async def execute(
        self, 
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute the settlement strategy.
        
        Args:
            payment_hash: The payment hash
            invoice: The invoice to settle
            preimage_hex: The preimage in hex format
            context: Additional context for the settlement
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Result dictionary
        """
        pass
    
    async def update_invoice_status(
        self, 
        invoice_id: str, 
        status: str, 
        conn=None
    ) -> Tuple[bool, Optional[TaprootInvoice]]:
        """
        Update the status of an invoice.
        
        Args:
            invoice_id: The ID of the invoice to update
            status: The new status
            conn: Optional database connection
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Updated invoice if successful, None otherwise
        """
        updated_invoice = await update_invoice_status(invoice_id, status, conn=conn)
        if not updated_invoice or updated_invoice.status != status:
            log_error(TRANSFER, f"Failed to update invoice {invoice_id} status in database")
            return False, None
        return True, updated_invoice
    
    async def record_asset_transaction(
        self,
        wallet_id: str,
        asset_id: str,
        amount: int,
        tx_type: str,
        payment_hash: str,
        description: str,
        conn=None
    ) -> bool:
        """
        Record an asset transaction.
        
        Args:
            wallet_id: The wallet ID
            asset_id: The asset ID
            amount: The transaction amount
            tx_type: The transaction type (credit/debit)
            payment_hash: The payment hash
            description: The transaction description
            conn: Optional database connection
            
        Returns:
            Success status (bool)
        """
        try:
            await record_asset_transaction(
                wallet_id=wallet_id,
                asset_id=asset_id,
                amount=amount,
                tx_type=tx_type,
                payment_hash=payment_hash,
                description=description,
                conn=conn
            )
            return True
        except Exception as e:
            log_error(TRANSFER, f"Failed to record asset transaction: {str(e)}")
            return False
    
    def format_result(
        self,
        payment_hash: str,
        preimage_hex: str,
        is_internal: bool = False,
        is_self_payment: bool = False,
        lightning_settled: bool = False,
        updated_invoice: Optional[TaprootInvoice] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Format the result of a settlement operation.
        
        Args:
            payment_hash: The payment hash
            preimage_hex: The preimage in hex format
            is_internal: Whether this is an internal payment
            is_self_payment: Whether this is a self-payment
            lightning_settled: Whether this was settled via Lightning
            updated_invoice: The updated invoice
            additional_data: Additional data to include in the result
            
        Returns:
            Result dictionary
        """
        result = {
            "success": True,
            "payment_hash": payment_hash,
            "preimage": preimage_hex,
            "updated_invoice": updated_invoice
        }
        
        if is_internal:
            result["is_internal"] = True
            result["is_self_payment"] = is_self_payment
        
        if lightning_settled:
            result["lightning_settled"] = lightning_settled
            
        if additional_data:
            result.update(additional_data)
            
        return result


class InternalPaymentStrategy(SettlementStrategy):
    """Strategy for settling internal payments without sender information."""
    
    async def execute(
        self, 
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute the internal payment settlement strategy.
        
        Args:
            payment_hash: The payment hash
            invoice: The invoice to settle
            preimage_hex: The preimage in hex format
            context: Additional context for the settlement
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Result dictionary
        """
        with ErrorContext("settle_internal_payment", TRANSFER):
            if not invoice:
                log_error(TRANSFER, f"No invoice found with payment_hash: {payment_hash}")
                return False, {"error": "Invoice not found"}
            
            is_self_payment = context.get("is_self_payment", False)
            
            # Use transaction context manager to ensure atomicity
            async with transaction() as conn:
                # Update invoice status to paid
                status_updated, updated_invoice = await self.update_invoice_status(invoice.id, "paid", conn=conn)
                if not status_updated:
                    return False, {"error": "Failed to update invoice status"}
                
                # Credit the recipient
                credit_success = await self.record_asset_transaction(
                    wallet_id=invoice.wallet_id,
                    asset_id=invoice.asset_id,
                    amount=invoice.asset_amount,
                    tx_type="credit",
                    payment_hash=payment_hash,
                    description=invoice.description or "",
                    conn=conn
                )
                
                if not credit_success:
                    return False, {"error": "Failed to record asset transaction"}
            
            payment_type = "self-payment" if is_self_payment else "internal payment"
            log_info(TRANSFER, f"Database updated: Invoice {invoice.id} status set to paid ({payment_type})")
            
            # Return success with details
            return True, self.format_result(
                payment_hash=payment_hash,
                preimage_hex=preimage_hex,
                is_internal=True,
                is_self_payment=is_self_payment,
                updated_invoice=updated_invoice
            )


class InternalPaymentWithSenderStrategy(SettlementStrategy):
    """Strategy for settling internal payments with sender information."""
    
    async def execute(
        self, 
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute the internal payment with sender settlement strategy.
        
        Args:
            payment_hash: The payment hash
            invoice: The invoice to settle
            preimage_hex: The preimage in hex format
            context: Additional context for the settlement
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Result dictionary
        """
        with ErrorContext("settle_internal_payment_with_sender", TRANSFER):
            if not invoice:
                log_error(TRANSFER, f"No invoice found with payment_hash: {payment_hash}")
                return False, {"error": "Invoice not found"}
                
            sender_info = context.get("sender_info", {})
            is_self_payment = context.get("is_self_payment", False)
            
            sender_wallet_id = sender_info.get("wallet_id")
            sender_user_id = sender_info.get("user_id")
            
            if not sender_wallet_id or not sender_user_id:
                log_error(TRANSFER, f"Missing sender information for payment: {payment_hash}")
                return False, {"error": "Incomplete sender information"}
            
            # Use our standardized asset ID resolution function
            debit_asset_id = resolve_asset_id(sender_info.get("asset_id"), invoice.asset_id)
            
            # Use transaction context manager to ensure atomicity
            async with transaction() as conn:
                # 1. Update invoice status to paid
                status_updated, updated_invoice = await self.update_invoice_status(invoice.id, "paid", conn=conn)
                if not status_updated:
                    return False, {"error": "Failed to update invoice status"}
                
                # 2. Credit the recipient (record transaction and update balance)
                credit_success = await self.record_asset_transaction(
                    wallet_id=invoice.wallet_id,
                    asset_id=invoice.asset_id,
                    amount=invoice.asset_amount,
                    tx_type="credit",
                    payment_hash=payment_hash,
                    description=invoice.description or "",
                    conn=conn
                )
                
                # 3. Debit the sender (record transaction and update balance)
                debit_success = await self.record_asset_transaction(
                    wallet_id=sender_wallet_id,
                    asset_id=debit_asset_id,
                    amount=invoice.asset_amount,
                    tx_type="debit",
                    payment_hash=payment_hash,
                    description=invoice.description or "",
                    conn=conn
                )
                
                if not credit_success or not debit_success:
                    return False, {"error": "Failed to record asset transactions"}
            
            payment_type = "self-payment" if is_self_payment else "internal payment"
            log_info(TRANSFER, f"Database updated: Invoice {invoice.id} status set to paid ({payment_type})")
            log_info(TRANSFER, f"Asset balance updated for both sender and recipient, amount={invoice.asset_amount}")
            
            # Return success with details
            return True, self.format_result(
                payment_hash=payment_hash,
                preimage_hex=preimage_hex,
                is_internal=True,
                is_self_payment=is_self_payment,
                updated_invoice=updated_invoice
            )


class LightningPaymentStrategy(SettlementStrategy):
    """Strategy for settling Lightning network payments."""
    
    async def execute(
        self, 
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute the Lightning payment settlement strategy.
        
        Args:
            payment_hash: The payment hash
            invoice: The invoice to settle
            preimage_hex: The preimage in hex format
            context: Additional context for the settlement
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Result dictionary
        """
        with ErrorContext("settle_lightning_payment", TRANSFER):
            node = context.get("node")
            if not node:
                return False, {"error": "Node not provided"}
                
            # Convert the preimage to bytes
            preimage_bytes = bytes.fromhex(preimage_hex)

            # Create settlement request
            settle_request = invoices_pb2.SettleInvoiceMsg(
                preimage=preimage_bytes
            )

            # Flag to track Lightning settlement
            lightning_settled = False
            error_message = None
            
            try:
                # Settle the invoice
                await node.invoices_stub.SettleInvoice(settle_request)
                log_info(TRANSFER, f"Lightning invoice {payment_hash[:8]}... successfully settled")
                lightning_settled = True
            except grpc.aio.AioRpcError as e:
                # Check if already settled
                if "invoice is already settled" in e.details().lower():
                    log_info(TRANSFER, f"Lightning invoice {payment_hash[:8]}... was already settled on the node")
                    lightning_settled = True
                else:
                    error_message = f"gRPC error in settle_invoice: {e.code()}: {e.details()}"
                    log_error(TRANSFER, error_message)
            
            # If Lightning settlement failed, stop here
            if not lightning_settled:
                return False, {"error": error_message or "Lightning settlement failed"}
            
            # Update the invoice status in the database if we have an invoice record
            updated_invoice = None
            if invoice:
                # Use transaction context manager to ensure atomicity
                async with transaction() as conn:
                    status_updated, updated_invoice = await self.update_invoice_status(invoice.id, "paid", conn=conn)
                
                if status_updated:
                    log_info(TRANSFER, f"Database updated: Invoice {invoice.id} status set to paid")
                else:
                    log_error(TRANSFER, f"Failed to update invoice {invoice.id} status in database")
                    # Note: We don't fail the operation here since the Lightning settlement succeeded
            
            # Return success with details
            return True, self.format_result(
                payment_hash=payment_hash,
                preimage_hex=preimage_hex,
                lightning_settled=lightning_settled,
                updated_invoice=updated_invoice
            )


class SettlementService:
    """
    Centralized service for handling all invoice settlement operations.
    Provides consistent behavior across different payment types while
    preserving the unique aspects of each.
    """
    
    # Class-level cache to track settled payment hashes
    _settled_payment_hashes = set()
    
    # Class-level lock for cache operations
    _cache_lock = asyncio.Lock()
    
    # Strategy instances
    _internal_strategy = InternalPaymentStrategy()
    _internal_with_sender_strategy = InternalPaymentWithSenderStrategy()
    _lightning_strategy = LightningPaymentStrategy()
    
    @classmethod
    def _determine_payment_type(cls, **kwargs) -> str:
        """
        Determine the payment type based on the provided parameters.
        
        Args:
            **kwargs: Keyword arguments to determine the payment type
            
        Returns:
            The payment type as a string
        """
        is_internal = kwargs.get("is_internal", False)
        sender_info = kwargs.get("sender_info")
        
        if is_internal:
            if sender_info:
                return "internal_with_sender"
            else:
                return "internal"
        else:
            return "lightning"
    
    @classmethod
    def _get_settlement_strategy(cls, payment_type: str) -> SettlementStrategy:
        """
        Get the appropriate settlement strategy for the given payment type.
        
        Args:
            payment_type: The payment type
            
        Returns:
            The settlement strategy
        """
        if payment_type == "internal_with_sender":
            return cls._internal_with_sender_strategy
        elif payment_type == "internal":
            return cls._internal_strategy
        else:  # lightning
            return cls._lightning_strategy
    
    @classmethod
    async def settle_invoice(
        cls,
        payment_hash: str,
        node,
        is_internal: bool = False,
        is_self_payment: bool = False,
        user_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        sender_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Settle an invoice using the appropriate strategy based on payment type.
        
        Args:
            payment_hash: The payment hash of the invoice to settle
            node: The TaprootAssetsNodeExtension instance
            is_internal: Whether this is an internal payment (between users on this node)
            is_self_payment: Whether this is a self-payment (same user)
            user_id: Optional user ID for notification
            wallet_id: Optional wallet ID for balance updates
            sender_info: Optional information about the sender for internal payments
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Optional result data dictionary
        """
        log_context = "internal payment" if is_internal else "Lightning payment"
        with ErrorContext(f"settle_invoice_{log_context}", TRANSFER):
            with LogContext(TRANSFER, f"settling invoice {payment_hash[:8]}... ({log_context})", log_level="info"):
                # Check if already settled in memory cache
                is_settled = False
                async with cls._cache_lock:
                    is_settled = payment_hash in cls._settled_payment_hashes
                    
                if is_settled:
                    log_info(TRANSFER, f"Invoice {payment_hash[:8]}... already marked as settled in memory, skipping")
                    return True, {"already_settled": True}
                
                # Check if already settled in database
                invoice = await get_invoice_by_payment_hash(payment_hash)
                if invoice and invoice.status == "paid":
                    log_info(TRANSFER, f"Invoice {payment_hash[:8]}... already paid in database, skipping")
                    # Add to memory cache to avoid future DB lookups
                    async with cls._cache_lock:
                        cls._settled_payment_hashes.add(payment_hash)
                    return True, {"already_settled": True}
                
                # Get or generate preimage
                preimage_hex = await cls._get_or_generate_preimage(node, payment_hash)
                if not preimage_hex:
                    log_error(TRANSFER, f"Failed to get or generate preimage for {payment_hash[:8]}...")
                    return False, {"error": "No preimage available"}
                
                # Determine payment type and get appropriate strategy
                payment_type = cls._determine_payment_type(
                    is_internal=is_internal,
                    sender_info=sender_info
                )
                strategy = cls._get_settlement_strategy(payment_type)
                
                # Prepare context for the strategy
                context = {
                    "node": node,
                    "is_self_payment": is_self_payment,
                    "user_id": user_id,
                    "wallet_id": wallet_id,
                    "sender_info": sender_info
                }
                
                # Execute the strategy
                success, result = await strategy.execute(
                    payment_hash, invoice, preimage_hex, context
                )
                
                # If successful, track settlement
                if success:
                    async with cls._cache_lock:
                        cls._settled_payment_hashes.add(payment_hash)
                    
                    # For Lightning payments, update asset balance if invoice exists
                    if not is_internal and invoice:
                        # Update asset balance if it's not an internal payment
                        async with transaction() as conn:
                            await cls._update_asset_balance(
                                invoice.wallet_id,
                                invoice.asset_id,
                                invoice.asset_amount,
                                payment_hash,
                                invoice.description,
                                conn=conn
                            )
                    
                    # Send WebSocket notifications if invoice exists
                    if invoice:
                        # Send WebSocket notifications
                        await cls._send_settlement_notifications(
                            invoice, result.get("updated_invoice"), node
                        )
                
                return success, result
    
    @classmethod
    async def record_payment(
        cls,
        payment_hash: str,
        payment_request: str,
        asset_id: str,
        asset_amount: int,
        fee_sats: int,
        user_id: str,
        wallet_id: str,
        description: Optional[str] = None,
        preimage: Optional[str] = None,
        is_internal: bool = False,
        is_self_payment: bool = False,
        conn=None
    ) -> Tuple[bool, Optional[TaprootPayment]]:
        """
        Record a payment in the database with proper transaction handling to ensure atomicity.
        
        Args:
            payment_hash: Payment hash
            payment_request: Original payment request
            asset_id: Asset ID
            asset_amount: Amount of the asset (not the fee)
            fee_sats: Fee in satoshis (actual fee, not the limit)
            user_id: User ID
            wallet_id: Wallet ID
            description: Optional description
            preimage: Optional preimage
            is_internal: Whether this is an internal payment
            is_self_payment: Whether this is a self-payment
            conn: Optional database connection to reuse
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Optional payment record
        """
        with ErrorContext("record_payment", PAYMENT):
            log_info(PAYMENT, f"Recording payment: hash={payment_hash[:8]}..., asset_amount={asset_amount}, fee_sats={fee_sats}")
            
            # Check if we've already processed this payment hash to avoid duplicates
            is_processed = False
            async with cls._cache_lock:
                is_processed = payment_hash in cls._settled_payment_hashes
                
            if is_processed and is_internal:
                # For internal payments, we already handled both sides in settle_invoice
                # Just create the payment record for notification purposes
                try:
                    payment_record = await create_payment_record(
                        payment_hash=payment_hash,
                        payment_request=payment_request,
                        asset_id=asset_id,
                        asset_amount=asset_amount,
                        fee_sats=fee_sats,
                        user_id=user_id,
                        wallet_id=wallet_id,
                        description=description or "",
                        preimage=preimage or "",
                        conn=conn
                    )
                    
                    log_info(PAYMENT, f"Internal payment record created for notification purposes: {payment_hash[:8]}...")
                    return True, payment_record
                except Exception as e:
                    log_warning(PAYMENT, f"Failed to create payment record for notification: {str(e)}")
                    return False, None
            elif is_processed:
                log_info(PAYMENT, f"Payment {payment_hash[:8]}... already processed, skipping record creation")
                return True, None
                
            # Wait a short time to allow any in-progress settlements to complete
            await asyncio.sleep(1.0)
            
            # Use transaction context manager with retry capability
            async with transaction(conn=conn, max_retries=5, retry_delay=0.2) as tx_conn:
                try:
                    # Check if the invoice is already paid
                    invoice = await get_invoice_by_payment_hash(payment_hash, conn=tx_conn)
                    if invoice and invoice.status == "paid":
                        log_info(PAYMENT, f"Invoice for payment {payment_hash[:8]}... is already paid, skipping payment record")
                        return True, None
                    
                    # Record the payment
                    payment_record = await create_payment_record(
                        payment_hash=payment_hash,
                        payment_request=payment_request,
                        asset_id=asset_id,
                        asset_amount=asset_amount,
                        fee_sats=fee_sats,
                        user_id=user_id,
                        wallet_id=wallet_id,
                        description=description or "",
                        preimage=preimage or "",
                        conn=tx_conn
                    )
                    
                    # Only create asset transaction if this is not an internal payment
                    if not is_internal:
                        # Get the strategy instance to use its record_asset_transaction method
                        strategy = cls._internal_strategy
                        
                        # Record the transaction
                        await strategy.record_asset_transaction(
                            wallet_id=wallet_id,
                            asset_id=asset_id,
                            amount=asset_amount,
                            tx_type="debit",  # Outgoing payment
                            payment_hash=payment_hash,
                            description=description or "",
                            conn=tx_conn
                        )
                    
                    # Add to settled payment hashes set
                    async with cls._cache_lock:
                        cls._settled_payment_hashes.add(payment_hash)
                    
                    log_info(PAYMENT, f"Payment record created successfully for hash={payment_hash[:8]}...")
                except Exception as e:
                    log_error(PAYMENT, f"Failed to record payment: {str(e)}")
                    return False, None
            
            # Send notifications after the transaction is committed
            try:
                await NotificationService.notify_transaction_complete(
                    user_id=user_id,
                    wallet_id=wallet_id,
                    payment_hash=payment_hash,
                    asset_id=asset_id,
                    asset_amount=asset_amount,
                    tx_type="debit",
                    description=description,
                    fee_sats=fee_sats,
                    is_internal=is_internal,
                    is_self_payment=is_self_payment
                )
            except Exception as e:
                log_warning(PAYMENT, f"Payment recorded but notification failed: {str(e)}")
            
            return True, payment_record
    
    @classmethod
    async def _get_or_generate_preimage(cls, node, payment_hash: str) -> Optional[str]:
        """Get an existing preimage or generate a new one if needed."""
        # Try to get existing preimage
        preimage_hex = node._get_preimage(payment_hash)
        
        # Generate a new one if not found
        if not preimage_hex:
            log_info(TRANSFER, f"No preimage found for {payment_hash[:8]}..., generating one")
            preimage = hashlib.sha256(f"{payment_hash}_{time.time()}".encode()).digest()
            preimage_hex = preimage.hex()
            # Store it
            node._store_preimage(payment_hash, preimage_hex)
            
        return preimage_hex
    
    @classmethod
    @with_transaction
    async def _update_asset_balance(
        cls,
        wallet_id: str,
        asset_id: str,
        amount: int,
        payment_hash: str,
        description: Optional[str] = None,
        conn=None
    ) -> bool:
        """
        Update the asset balance for a received payment.
        
        Args:
            wallet_id: Wallet ID to update
            asset_id: Asset ID to update
            amount: Amount to credit
            payment_hash: Payment hash for reference
            description: Optional description for the transaction
            conn: Optional database connection to reuse
            
        Returns:
            bool: Success status
        """
        with ErrorContext("update_asset_balance", TRANSFER):
            # Use the strategy instance to record the asset transaction
            strategy = cls._internal_strategy
            success = await strategy.record_asset_transaction(
                wallet_id=wallet_id,
                asset_id=asset_id,
                amount=amount,
                tx_type="credit",  # Incoming payment
                payment_hash=payment_hash,
                description=description or "",
                conn=conn
            )
            
            if success:
                log_info(TRANSFER, f"Asset balance updated for asset_id={asset_id}, amount={amount}")
            
            return success
    
    @classmethod
    async def _send_settlement_notifications(
        cls,
        invoice: TaprootInvoice,
        updated_invoice: Optional[TaprootInvoice],
        node
    ) -> None:
        """
        Send WebSocket notifications for invoice settlement.
        
        Args:
            invoice: The settled invoice
            updated_invoice: The updated invoice from the database
            node: Node extension instance for fetching assets
        """
        try:
            # Skip if no user ID to notify
            if not invoice.user_id:
                return
                
            # Get paid timestamp
            paid_at = None
            if updated_invoice and updated_invoice.paid_at:
                paid_at = updated_invoice.paid_at.isoformat() if hasattr(updated_invoice.paid_at, "isoformat") else str(updated_invoice.paid_at)
            
            # Send invoice update notification
            await NotificationService.notify_invoice_update(
                invoice.user_id, 
                {
                    "id": invoice.id,
                    "payment_hash": invoice.payment_hash,
                    "status": "paid",
                    "asset_id": invoice.asset_id,
                    "asset_amount": invoice.asset_amount,
                    "paid_at": paid_at
                }
            )
            
            # Get updated assets for notifications
            try:
                # Get assets with channel info
                assets = await node.list_assets()
                
                # Filter to only include assets with channel info
                filtered_assets = [asset for asset in assets if asset.get("channel_info")]
                
                # Add user balance information
                for asset in filtered_assets:
                    asset_id_check = asset.get("asset_id")
                    if asset_id_check:
                        balance = await get_asset_balance(invoice.wallet_id, asset_id_check)
                        asset["user_balance"] = balance.balance if balance else 0
                
                # Send assets update notification
                if filtered_assets:
                    await NotificationService.notify_assets_update(invoice.user_id, filtered_assets)
            except Exception as asset_err:
                log_error(TRANSFER, f"Failed to send asset updates notification: {str(asset_err)}")
                
        except Exception as e:
            log_error(TRANSFER, f"Failed to send settlement notifications: {str(e)}")
