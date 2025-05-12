import asyncio
import hashlib
import time
from typing import Optional, Tuple, Any, Dict, Set
import grpc
import grpc.aio
from loguru import logger

from .taproot_adapter import (
    taprootassets_pb2,
    invoices_pb2
)

# Import database functions from crud re-exports
from ..crud import (
    get_invoice_by_payment_hash,
    is_internal_payment,
    is_self_payment
)

# Import Settlement Service
from ..services.settlement_service import SettlementService
from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, TRANSFER, LogContext
)

class TaprootTransferManager:
    """
    Handles Taproot Asset transfer monitoring.
    This class is responsible for monitoring asset transfers and settling HODL invoices.
    Implemented as a singleton to prevent multiple initializations.
    """
    # Class variables for tracking monitoring state and singleton instance
    _is_monitoring = False
    _instance = None
    
    @classmethod
    def get_instance(cls, node):
        """
        Get or create the singleton instance.
        
        Args:
            node: The TaprootAssetsNodeExtension instance
            
        Returns:
            The singleton TaprootTransferManager instance
        """
        if cls._instance is None:
            cls._instance = cls(node)
            logger.info("TaprootTransferManager initialized")
        elif cls._instance.node != node:
            # Update the node reference if needed
            cls._instance.node = node
            logger.debug("TaprootTransferManager node reference updated")
        return cls._instance

    def __init__(self, node):
        """
        Initialize the transfer manager with a reference to the node.
        This should only be called once through get_instance().

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node

    async def monitor_asset_transfers(self):
        """Monitor asset transfers and settle HODL invoices when transfers complete."""
        if TaprootTransferManager._is_monitoring:
            logger.info("Monitoring already active, ignoring duplicate call")
            return
            
        TaprootTransferManager._is_monitoring = True
        logger.info("Starting asset transfer monitoring")

        # Define heartbeat interval
        HEARTBEAT_INTERVAL = 60  # 1 minute between heartbeats

        # Set up last cache size for efficient logging
        last_cache_size = 0
        last_heartbeat_time = time.time()

        async def check_unprocessed_payments():
            """Check for unprocessed payments and attempt to settle them."""
            try:
                # Get all script key mappings
                script_key_mappings = list(self.node.invoice_manager._script_key_to_payment_hash.keys())
                if not script_key_mappings:
                    return 0
                    
                # Count of newly processed payments
                newly_processed = 0
                    
                for script_key in script_key_mappings:
                    payment_hash = self.node.invoice_manager._get_payment_hash_from_script_key(script_key)
                    
                    # Skip payments without preimage
                    preimage = self.node._get_preimage(payment_hash)
                    if not payment_hash or not preimage:
                        continue
                    
                    # Check if already settled in database
                    invoice = await get_invoice_by_payment_hash(payment_hash)
                    if invoice and invoice.status == "paid":
                        continue
                    
                    # Check if this is an internal payment
                    is_internal = await is_internal_payment(payment_hash)
                    
                    # Check if this is a self-payment if we have wallet info
                    is_self_payment = False
                    user_id = None
                    wallet_id = None
                    
                    if hasattr(self.node, 'wallet') and self.node.wallet:
                        user_id = self.node.wallet.user
                        wallet_id = self.node.wallet.id
                        if user_id and invoice:
                            is_self_payment = await is_self_payment(payment_hash, user_id)
                    
                    # Attempt settlement with Settlement Service
                    logger.info(f"Found unprocessed payment, attempting settlement")
                    
                    try:
                        success, result = await SettlementService.settle_invoice(
                            payment_hash=payment_hash,
                            node=self.node,
                            is_internal=is_internal,
                            is_self_payment=is_self_payment,
                            user_id=user_id,
                            wallet_id=wallet_id
                        )
                        
                        if not success:
                            from ..error_utils import handle_error
                            error_msg = result.get('error', 'Unknown error')
                            error_result = handle_error("settle_payment", Exception(error_msg), payment_hash)
                    except Exception as e:
                        from ..error_utils import handle_error
                        error_result = handle_error("check_unprocessed_payments", e, payment_hash)
                        logger.error(f"Exception during settlement: {error_result['error']}")
                        continue
                    
                    # Track newly processed payments
                    if success:
                        newly_processed += 1
                
                # Return the number of newly processed payments
                return newly_processed
            except Exception as e:
                logger.error(f"Error checking unprocessed payments: {str(e)}")
                return 0

        async def _heartbeat_loop():
            """
            Periodically check for unprocessed payments and clean up expired preimages.
            Only logs when there's something meaningful to report.
            """
            nonlocal last_cache_size, last_heartbeat_time
            
            while True:
                try:
                    current_time = time.time()
                    
                    # Perform cleanup and settlement at each heartbeat interval
                    if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                        last_heartbeat_time = current_time
                        
                        # Clean up expired preimages
                        expired_count = await self._cleanup_preimage_cache()
                        
                        # Check for and process unprocessed payments
                        processed_count = await check_unprocessed_payments()
                        
                        # Get current cache size - we can't directly access the cache size anymore
                        # Just log the processed and expired counts
                        current_cache_size = 0  # Placeholder, not used for logging
                        
                        # Only log if action was taken
                        if expired_count > 0 or processed_count > 0:
                            logger.info(f"Heartbeat: Expired preimages: {expired_count}, " +
                                       f"Newly processed: {processed_count}")

                    # Sleep for a shorter period to allow cancellation
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    logger.info("Heartbeat task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in heartbeat: {str(e)}")
                    await asyncio.sleep(10)

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(_heartbeat_loop())

        try:
            # Subscribe to send events - simpler without multiple retries
            request = taprootassets_pb2.SubscribeSendEventsRequest()
            send_events = self.node.stub.SubscribeSendEvents(request)
            logger.info("Successfully subscribed to send events")

            # Process incoming events
            async for event in send_events:
                logger.debug("Received send event")
                # Process event logic here
        except Exception as e:
            logger.error(f"Error in asset transfer monitoring: {str(e)}")
        finally:
            # Cancel heartbeat task
            if 'heartbeat_task' in locals():
                heartbeat_task.cancel()
            
            # Reset monitoring state to allow future attempts
            TaprootTransferManager._is_monitoring = False

    async def monitor_invoice(self, payment_hash: str):
        """
        Monitor a specific invoice for state changes.
        """
        logger.info(f"Monitoring invoice {payment_hash}")

        try:
            # Get the invoice from database to determine payment type
            invoice = await get_invoice_by_payment_hash(payment_hash)
            
            # Determine if this is an internal payment
            is_internal = await is_internal_payment(payment_hash)
            
            # For internal payments, handle settlement via SettlementService
            if is_internal:
                # Check if it's a self-payment (same user) or just internal (different users)
                is_self = False
                user_id = None
                wallet_id = None
                
                if hasattr(self.node, 'wallet') and self.node.wallet:
                    user_id = self.node.wallet.user
                    wallet_id = self.node.wallet.id
                    if user_id:
                        is_self = await is_self_payment(payment_hash, user_id)
                
                if is_self:
                    logger.info(f"Self-payment detected for {payment_hash}, using SettlementService")
                else:
                    logger.info(f"Internal payment detected for {payment_hash}, using SettlementService")
                
                # Use Settlement Service for internal payments
                success, result = await SettlementService.settle_invoice(
                    payment_hash=payment_hash,
                    node=self.node,
                    is_internal=True,
                    is_self_payment=is_self,
                    user_id=user_id,
                    wallet_id=wallet_id
                )
                
                if success:
                    logger.info(f"Internal payment successfully settled: {payment_hash}")
                else:
                    from ..error_utils import handle_error
                    error_msg = result.get('error', 'Unknown error')
                    error_result = handle_error("settle_internal_payment", Exception(error_msg), payment_hash)
                    
                return
            
            # Continue with Lightning monitoring for external payments
            # Convert payment hash to bytes
            payment_hash_bytes = bytes.fromhex(payment_hash) if isinstance(payment_hash, str) else payment_hash
            request = invoices_pb2.SubscribeSingleInvoiceRequest(r_hash=payment_hash_bytes)

            # Subscribe to invoice updates
            async for invoice in self.node.invoices_stub.SubscribeSingleInvoice(request):
                # Map state to human-readable form
                state_map = {0: "OPEN", 1: "SETTLED", 2: "CANCELED", 3: "ACCEPTED"}
                state_name = state_map.get(invoice.state, f"UNKNOWN({invoice.state})")
                logger.info(f"Invoice {payment_hash}: {state_name}")

                # Process ACCEPTED state (3)
                if invoice.state == 3:  # ACCEPTED state
                    logger.info(f"Invoice {payment_hash} is ACCEPTED - attempting to settle")
                    
                    # Extract and store script key if available
                    script_key_hex = await self._extract_script_key_from_invoice(invoice)
                    if script_key_hex:
                        self.node.invoice_manager._store_script_key_mapping(script_key_hex, payment_hash)
                    
                    # Get wallet info if available
                    user_id = None
                    wallet_id = None
                    if hasattr(self.node, 'wallet') and self.node.wallet:
                        user_id = self.node.wallet.user
                        wallet_id = self.node.wallet.id
                    
                    # Delegate to SettlementService for settlement
                    success, result = await SettlementService.settle_invoice(
                        payment_hash=payment_hash,
                        node=self.node,
                        is_internal=False,
                        is_self_payment=False,
                        user_id=user_id,
                        wallet_id=wallet_id
                    )
                    
                    if success:
                        logger.info(f"Lightning payment successfully settled: {payment_hash}")
                    else:
                        from ..error_utils import handle_error
                        error_msg = result.get('error', 'Unknown error')
                        error_result = handle_error("settle_lightning_payment", Exception(error_msg), payment_hash)
                    
                    break
                    
                # Process already SETTLED state (1)
                elif invoice.state == 1:  # SETTLED state
                    logger.info(f"Invoice {payment_hash} is already SETTLED")
                    break
                    
                # Process CANCELED state (2)
                elif invoice.state == 2:  # CANCELED state
                    logger.warning(f"Invoice {payment_hash} was CANCELED")
                    break

        except Exception as e:
            from ..error_utils import handle_error
            error_result = handle_error("monitor_invoice", e, payment_hash)

    async def _cleanup_preimage_cache(self) -> int:
        """
        Clean up expired preimages from the cache.
        
        Note: We can't directly access the cache anymore, so this is a no-op.
        The cache utility handles expiration automatically.
        
        Returns:
            int: Number of expired entries removed (always 0 now)
        """
        # The cache utility handles expiration automatically
        # This method is kept for compatibility but doesn't do anything now
        return 0
        
    async def _extract_script_key_from_invoice(self, invoice) -> Optional[str]:
        """Extract script key from invoice HTLCs."""
        if not hasattr(invoice, 'htlcs') or not invoice.htlcs:
            return None
            
        for htlc in invoice.htlcs:
            if not hasattr(htlc, 'custom_records') or not htlc.custom_records:
                continue
                
            # Process asset transfer record (65543)
            if 65543 in htlc.custom_records:
                try:
                    value = htlc.custom_records[65543]
                    
                    # Extract asset ID marker
                    asset_id_marker = bytes.fromhex("0020")
                    asset_id_pos = value.find(asset_id_marker)
                    
                    if asset_id_pos >= 0:
                        asset_id_end = asset_id_pos + 2 + 32
                        
                        # Extract script key
                        script_key_marker = bytes.fromhex("0140")
                        script_key_pos = value.find(script_key_marker, asset_id_end)
                        
                        if script_key_pos >= 0:
                            script_key_start = script_key_pos + 2
                            script_key_end = script_key_start + 33
                            script_key = value[script_key_start:script_key_end]
                            return script_key.hex()
                except Exception as e:
                    from ..error_utils import handle_error
                    error_result = handle_error("extract_script_key", e)
        
        return None
