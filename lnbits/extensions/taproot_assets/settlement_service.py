"""
Centralized Settlement Service for Taproot Assets extension.
Handles all invoice settlement logic consistently across different payment types.
"""
import asyncio
import hashlib
import time
from typing import Optional, Dict, Any, Tuple, List
import grpc
import grpc.aio
from loguru import logger

from .wallets.taproot_adapter import invoices_pb2
from .notification_service import NotificationService
from .models import TaprootInvoice, TaprootPayment
from .db_utils import transaction, with_transaction

# Import database functions from crud re-exports
from .crud import (
    get_invoice_by_payment_hash,
    update_invoice_status,
    is_internal_payment,
    is_self_payment,
    record_asset_transaction,
    get_asset_balance,
    create_payment_record
)

from .logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, PAYMENT, TRANSFER, LogContext
)
from .error_utils import ErrorContext

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
    
    # We're now using the global transaction lock from db_utils.py
    # instead of a class-specific lock to prevent deadlocks
    
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
        Settle an invoice using the appropriate method based on payment type.
        
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
                # First check if already settled
                is_settled = False
                async with cls._cache_lock:
                    is_settled = payment_hash in cls._settled_payment_hashes
                    
                if is_settled:
                    log_debug(TRANSFER, f"Invoice {payment_hash[:8]}... already marked as settled, skipping")
                    return True, {"already_settled": True}
                
                # Get the invoice from database
                invoice = await get_invoice_by_payment_hash(payment_hash)
                if invoice and invoice.status == "paid":
                    log_debug(TRANSFER, f"Invoice {payment_hash[:8]}... is already marked as paid in the database, skipping")
                    cls._settled_payment_hashes.add(payment_hash)
                    return True, {"already_settled": True}
                
                # Get or generate preimage
                preimage_hex = await cls._get_or_generate_preimage(node, payment_hash)
                if not preimage_hex:
                    log_error(TRANSFER, f"Failed to get or generate preimage for {payment_hash[:8]}...")
                    return False, {"error": "No preimage available"}
                
                # Process based on payment type
                if is_internal:
                    # For internal payments, handle both recipient and sender in one transaction
                    if sender_info and invoice:
                        success, result = await cls._settle_internal_payment_with_sender(
                            payment_hash, invoice, preimage_hex, 
                            is_self_payment, sender_info
                        )
                    else:
                        success, result = await cls._settle_internal_payment(
                            payment_hash, invoice, preimage_hex, 
                            is_self_payment, user_id, wallet_id
                        )
                else:
                    success, result = await cls._settle_lightning_payment(
                        payment_hash, invoice, preimage_hex, node
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
                                invoice.memo,
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
    async def _settle_internal_payment_with_sender(
        cls,
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        is_self_payment: bool = False,
        sender_info: Dict[str, Any] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Handle settlement for internal payments with sender information.
        This processes both sides of the transaction in a single atomic operation.
        """
        with ErrorContext("settle_internal_payment_with_sender", TRANSFER):
            if not invoice:
                log_error(TRANSFER, f"No invoice found with payment_hash: {payment_hash}")
                return False, {"error": "Invoice not found"}
                
            sender_wallet_id = sender_info.get("wallet_id")
            sender_user_id = sender_info.get("user_id")
            
            if not sender_wallet_id or not sender_user_id:
                log_error(TRANSFER, f"Missing sender information for payment: {payment_hash}")
                return False, {"error": "Incomplete sender information"}
            
            # Use transaction context manager to ensure atomicity
            async with transaction() as conn:
                # 1. Update invoice status to paid
                updated_invoice = await update_invoice_status(invoice.id, "paid", conn=conn)
                if not updated_invoice or updated_invoice.status != "paid":
                    log_error(TRANSFER, f"Failed to update invoice {invoice.id} status in database")
                    return False, {"error": "Failed to update invoice status"}
                
                # 2. Credit the recipient (record transaction and update balance)
                await record_asset_transaction(
                    wallet_id=invoice.wallet_id,
                    asset_id=invoice.asset_id,
                    amount=invoice.asset_amount,
                    tx_type="credit",
                    payment_hash=payment_hash,
                    memo=invoice.memo or "",
                    conn=conn
                )
                
                # 3. Debit the sender (record transaction and update balance)
                await record_asset_transaction(
                    wallet_id=sender_wallet_id,
                    asset_id=invoice.asset_id,
                    amount=invoice.asset_amount,
                    tx_type="debit",
                    payment_hash=payment_hash,
                    memo=invoice.memo or "",
                    conn=conn
                )
            
            payment_type = "self-payment" if is_self_payment else "internal payment"
            log_info(TRANSFER, f"Database updated: Invoice {invoice.id} status set to paid ({payment_type})")
            log_info(TRANSFER, f"Asset balance updated for both sender and recipient, amount={invoice.asset_amount}")
            
            # Return success with details
            return True, {
                "success": True,
                "payment_hash": payment_hash,
                "preimage": preimage_hex,
                "is_internal": True,
                "is_self_payment": is_self_payment,
                "updated_invoice": updated_invoice
            }
    
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
        memo: Optional[str] = None,
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
            memo: Optional memo
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
            # This is critical for preventing race conditions with settle_invoice
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
                        memo=memo or "",
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
            # This helps avoid race conditions between settle_invoice and record_payment
            await asyncio.sleep(1.0)
            
            # Use our improved transaction context manager with retry capability
            # If conn is provided, we'll reuse it, otherwise create a new one
            async with transaction(conn=conn, max_retries=5, retry_delay=0.2) as tx_conn:
                try:
                    # Check again inside the transaction if this payment has already been recorded
                    # This is a double-check to prevent race conditions
                    existing_payment = None
                    try:
                        # We don't have a direct method to check for existing payments by hash,
                        # but we can check if the invoice is already paid which would indicate
                        # the payment was already processed
                        invoice = await get_invoice_by_payment_hash(payment_hash, conn=tx_conn)
                        if invoice and invoice.status == "paid":
                            log_info(PAYMENT, f"Invoice for payment {payment_hash[:8]}... is already paid, skipping payment record")
                            return True, None
                    except Exception as check_err:
                        # If we can't check, proceed with creating the payment record
                        log_warning(PAYMENT, f"Failed to check for existing payment: {str(check_err)}")
                    
                    # Record the payment with the correct asset amount, not the fee
                    payment_record = await create_payment_record(
                        payment_hash=payment_hash,
                        payment_request=payment_request,
                        asset_id=asset_id,
                        asset_amount=asset_amount,  # Ensure this is the actual asset amount
                        fee_sats=fee_sats,  # This is the fee, separate from asset amount
                        user_id=user_id,
                        wallet_id=wallet_id,
                        memo=memo or "",
                        preimage=preimage or "",
                        conn=tx_conn
                    )
                    
                    # Only create asset transaction if this is not an internal payment
                    # For internal payments, both sides are handled in settle_invoice
                    if not is_internal:
                        # Record the transaction with the correct asset amount
                        tx_type = "debit"  # Outgoing payment
                        await record_asset_transaction(
                            wallet_id=wallet_id,
                            asset_id=asset_id,
                            amount=asset_amount,  # Use the correct asset amount here
                            tx_type=tx_type,
                            payment_hash=payment_hash,
                            fee=fee_sats,  # Fee is separate
                            memo=memo or "",
                            conn=tx_conn
                        )
                    
                    # Add to our settled payment hashes set to prevent duplicate processing
                    async with cls._cache_lock:
                        cls._settled_payment_hashes.add(payment_hash)
                    
                    # Transaction will be committed automatically when the context manager exits
                    log_info(PAYMENT, f"Payment record created successfully for hash={payment_hash[:8]}...")
                    
                    # Send notifications outside the transaction to avoid holding the lock
                    # during potentially slow network operations
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
                    asset_amount=asset_amount,  # Use correct asset amount in notification
                    tx_type="debit",
                    memo=memo,
                    fee_sats=fee_sats,
                    is_internal=is_internal,
                    is_self_payment=is_self_payment
                )
            except Exception as e:
                # Don't fail the whole operation if notifications fail
                log_warning(PAYMENT, f"Payment recorded but notification failed: {str(e)}")
            
            return True, payment_record
    
    # The below methods remain unchanged to minimize changes to the codebase
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
    async def _settle_internal_payment(
        cls,
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        is_self_payment: bool = False,
        user_id: Optional[str] = None,
        wallet_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Handle settlement for internal payments (including self-payments).
        These are processed through database updates rather than Lightning network.
        """
        with ErrorContext("settle_internal_payment", TRANSFER):
            if not invoice:
                log_error(TRANSFER, f"No invoice found with payment_hash: {payment_hash}")
                return False, {"error": "Invoice not found"}
            
            # Use transaction context manager to ensure atomicity
            async with transaction() as conn:
                # Update invoice status to paid
                updated_invoice = await update_invoice_status(invoice.id, "paid", conn=conn)
                if not updated_invoice or updated_invoice.status != "paid":
                    log_error(TRANSFER, f"Failed to update invoice {invoice.id} status in database")
                    return False, {"error": "Failed to update invoice status"}
                
                # Credit the recipient
                await record_asset_transaction(
                    wallet_id=invoice.wallet_id,
                    asset_id=invoice.asset_id,
                    amount=invoice.asset_amount,
                    tx_type="credit",
                    payment_hash=payment_hash,
                    memo=invoice.memo or "",
                    conn=conn
                )
            
            payment_type = "self-payment" if is_self_payment else "internal payment"
            log_info(TRANSFER, f"Database updated: Invoice {invoice.id} status set to paid ({payment_type})")
            
            # Return success with details
            return True, {
                "success": True,
                "payment_hash": payment_hash,
                "preimage": preimage_hex,
                "is_internal": True,
                "is_self_payment": is_self_payment,
                "updated_invoice": updated_invoice
            }
    
    @classmethod
    async def _settle_lightning_payment(
        cls,
        payment_hash: str,
        invoice: Optional[TaprootInvoice],
        preimage_hex: str,
        node
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Handle settlement for Lightning network payments.
        Uses HODL invoice settlement via the Lightning node.
        """
        with ErrorContext("settle_lightning_payment", TRANSFER):
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
                    updated_invoice = await update_invoice_status(invoice.id, "paid", conn=conn)
                
                if not updated_invoice or updated_invoice.status != "paid":
                    log_error(TRANSFER, f"Failed to update invoice {invoice.id} status in database")
                    # Note: We don't fail the operation here since the Lightning settlement succeeded
                else:
                    log_info(TRANSFER, f"Database updated: Invoice {invoice.id} status set to paid")
            
            # Return success with details
            return True, {
                "success": True,
                "payment_hash": payment_hash,
                "preimage": preimage_hex,
                "lightning_settled": lightning_settled,
                "updated_invoice": updated_invoice
            }
    
    @classmethod
    @with_transaction
    async def _update_asset_balance(
        cls,
        wallet_id: str,
        asset_id: str,
        amount: int,
        payment_hash: str,
        memo: Optional[str] = None,
        conn=None
    ) -> bool:
        """
        Update the asset balance for a received payment.
        
        Args:
            wallet_id: Wallet ID to update
            asset_id: Asset ID to update
            amount: Amount to credit
            payment_hash: Payment hash for reference
            memo: Optional memo for the transaction
            conn: Optional database connection to reuse
            
        Returns:
            bool: Success status
        """
        with ErrorContext("update_asset_balance", TRANSFER):
            # Record the asset transaction as a credit
            await record_asset_transaction(
                wallet_id=wallet_id,
                asset_id=asset_id,
                amount=amount,
                tx_type="credit",  # Incoming payment
                payment_hash=payment_hash,
                memo=memo or "",  # Use empty string if no memo provided
                conn=conn
            )
            log_info(TRANSFER, f"Asset balance updated for asset_id={asset_id}, amount={amount}")
            return True
    
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
            
            # Send invoice update notification through NotificationService
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
