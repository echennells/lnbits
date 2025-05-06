"""
Centralized Settlement Service for Taproot Assets extension.
Handles all invoice settlement logic consistently across different payment types.
"""
import asyncio
import hashlib
import time
from typing import Optional, Dict, Any, Tuple
import grpc
import grpc.aio
from loguru import logger

from .wallets.taproot_adapter import invoices_pb2
from .notification_service import NotificationService
from .models import TaprootInvoice

# Import database functions
from .crud import (
    get_invoice_by_payment_hash,
    update_invoice_status,
    record_asset_transaction,
    get_asset_balance,
    is_internal_payment,
    is_self_payment
)

from .logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, PAYMENT, TRANSFER, LogContext
)

class SettlementService:
    """
    Centralized service for handling all invoice settlement operations.
    Provides consistent behavior across different payment types while
    preserving the unique aspects of each.
    """
    
    # Class-level cache to track settled payment hashes
    _settled_payment_hashes = set()
    
    @classmethod
    async def settle_invoice(
        cls,
        payment_hash: str,
        node,
        is_internal: bool = False,
        is_self_payment: bool = False,
        user_id: Optional[str] = None,
        wallet_id: Optional[str] = None
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
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Optional result data dictionary
        """
        log_context = "internal payment" if is_internal else "Lightning payment"
        with LogContext(TRANSFER, f"settling invoice {payment_hash[:8]}... ({log_context})", log_level="info"):
            try:
                # First check if already settled
                if payment_hash in cls._settled_payment_hashes:
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
                    success, result = await cls._settle_internal_payment(
                        payment_hash, invoice, preimage_hex, is_self_payment, user_id, wallet_id
                    )
                else:
                    success, result = await cls._settle_lightning_payment(
                        payment_hash, invoice, preimage_hex, node
                    )
                
                # If successful, track settlement and update asset balance
                if success:
                    cls._settled_payment_hashes.add(payment_hash)
                    
                    # Update asset balance if invoice exists
                    if invoice:
                        await cls._update_asset_balance(
                            invoice.wallet_id,
                            invoice.asset_id,
                            invoice.asset_amount,
                            payment_hash,
                            invoice.memo
                        )
                        
                        # Send WebSocket notifications
                        await cls._send_settlement_notifications(
                            invoice, result.get("updated_invoice"), node
                        )
                
                return success, result
                
            except Exception as e:
                log_error(TRANSFER, f"Failed to settle invoice: {str(e)}", exc_info=True)
                return False, {"error": str(e)}
    
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
        try:
            if not invoice:
                log_error(TRANSFER, f"No invoice found with payment_hash: {payment_hash}")
                return False, {"error": "Invoice not found"}
                
            # Update invoice status to paid
            updated_invoice = await update_invoice_status(invoice.id, "paid")
            if not updated_invoice or updated_invoice.status != "paid":
                log_error(TRANSFER, f"Failed to update invoice {invoice.id} status in database")
                return False, {"error": "Failed to update invoice status"}
                
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
            
        except Exception as e:
            log_error(TRANSFER, f"Failed to settle internal payment: {str(e)}", exc_info=True)
            return False, {"error": str(e)}
    
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
        try:
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
                updated_invoice = await update_invoice_status(invoice.id, "paid")
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
            
        except Exception as e:
            log_error(TRANSFER, f"Failed to settle Lightning payment: {str(e)}", exc_info=True)
            return False, {"error": str(e)}
    
    @classmethod
    async def _update_asset_balance(
        cls,
        wallet_id: str,
        asset_id: str,
        amount: int,
        payment_hash: str,
        memo: Optional[str] = None
    ) -> bool:
        """
        Update the asset balance for a received payment.
        
        Args:
            wallet_id: Wallet ID to update
            asset_id: Asset ID to update
            amount: Amount to credit
            payment_hash: Payment hash for reference
            memo: Optional memo for the transaction
            
        Returns:
            bool: Success status
        """
        try:
            # Record the asset transaction as a credit
            await record_asset_transaction(
                wallet_id=wallet_id,
                asset_id=asset_id,
                amount=amount,
                tx_type="credit",  # Incoming payment
                payment_hash=payment_hash,
                memo=memo or ""  # Use empty string if no memo provided
            )
            log_info(TRANSFER, f"Asset balance updated for asset_id={asset_id}, amount={amount}")
            return True
        except Exception as e:
            log_error(TRANSFER, f"Failed to update asset balance: {str(e)}", exc_info=True)
            return False
    
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
