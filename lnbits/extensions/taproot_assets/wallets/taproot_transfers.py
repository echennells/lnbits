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

# Import database functions - only keeping what's needed for non-settlement operations
# Import from specific CRUD submodule
from ..crud.invoices import (
    get_invoice_by_payment_hash,
    is_internal_payment,
    is_self_payment
)

# Import Settlement Service
from ..settlement_service import SettlementService
from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, TRANSFER, LogContext
)

# Singleton tracking for monitoring instances
_monitoring_instances = set()

class TaprootTransferManager:
    """
    Handles Taproot Asset transfer monitoring.
    This class is responsible for monitoring asset transfers and settling HODL invoices.
    """
    # Class variables for tracking monitoring state
    _is_monitoring = False

    def __init__(self, node):
        """
        Initialize the transfer manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node
        # Add this instance to the set of monitoring instances
        global _monitoring_instances
        _monitoring_instances.add(self)
        logger.info("TaprootTransferManager initialized")

    async def manually_settle_invoice(
        self,
        payment_hash: str,
        script_key: Optional[str] = None
    ) -> bool:
        """
        Manually settle a HODL invoice. Used as a fallback if automatic settlement fails.

        Args:
            payment_hash: The payment hash of the invoice to settle
            script_key: Optional script key to use for lookup if payment hash is not found directly

        Returns:
            bool: True if settlement was successful, False otherwise
        """
        with LogContext(TRANSFER, f"manually settling invoice {payment_hash[:8]}...", log_level="info"):
            try:
                # Check if this is an internal payment
                is_internal = await is_internal_payment(payment_hash)
                
                # Try to get the preimage directly from the payment hash
                preimage_hex = self.node._get_preimage(payment_hash)
                
                # If not found and script key is provided, try to look up the payment hash
                if not preimage_hex and script_key:
                    mapped_payment_hash = self.node.invoice_manager._get_payment_hash_from_script_key(script_key)
                    if mapped_payment_hash:
                        preimage_hex = self.node._get_preimage(mapped_payment_hash)
                
                # Delegate to the settlement service
                success, _ = await SettlementService.settle_invoice(
                    payment_hash=payment_hash,
                    node=self.node,
                    is_internal=is_internal,
                    user_id=self.node.wallet.user if hasattr(self.node, 'wallet') and self.node.wallet else None,
                    wallet_id=self.node.wallet.id if hasattr(self.node, 'wallet') and self.node.wallet else None
                )
                
                return success
                    
            except Exception as e:
                log_error(TRANSFER, f"Failed to manually settle invoice: {str(e)}")
                return False

    async def monitor_asset_transfers(self):
        """
        Monitor asset transfers and settle HODL invoices when transfers complete.
        """
        # Use class-level flag to prevent duplicate monitoring
        if TaprootTransferManager._is_monitoring:
            logger.info("Monitoring already active, ignoring duplicate call")
            return
            
        TaprootTransferManager._is_monitoring = True
        logger.info("Starting asset transfer monitoring")

        RETRY_DELAY = 5  # seconds
        MAX_RETRIES = 3  # number of retries before giving up
        HEARTBEAT_INTERVAL = 300  # 5 minutes between heartbeats

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
                    if not payment_hash or payment_hash not in self.node._preimage_cache:
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
                    
                    success, _ = await SettlementService.settle_invoice(
                        payment_hash=payment_hash,
                        node=self.node,
                        is_internal=is_internal,
                        is_self_payment=is_self_payment,
                        user_id=user_id,
                        wallet_id=wallet_id
                    )
                    
                    # Track newly processed payments
                    if success:
                        newly_processed += 1
                
                # Return the number of newly processed payments
                return newly_processed
            except Exception as e:
                logger.error(f"Error checking unprocessed payments: {str(e)}")
                return 0

        async def log_heartbeat():
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
                        
                        # Get current cache size
                        current_cache_size = len(self.node._preimage_cache)
                        
                        # Only log if something changed or action was taken
                        if (current_cache_size != last_cache_size or 
                            expired_count > 0 or processed_count > 0):
                            logger.info(f"Heartbeat: Preimage cache size: {current_cache_size}, " +
                                       f"Expired: {expired_count}, Newly processed: {processed_count}")
                            last_cache_size = current_cache_size

                    # Sleep for a shorter period to allow cancellation
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    logger.info("Heartbeat task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in heartbeat: {str(e)}")
                    await asyncio.sleep(10)

        async def _cleanup_preimage_cache() -> int:
            """
            Clean up expired preimages from the cache.
            
            Returns:
                int: Number of expired entries removed
            """
            now = time.time()
            expired_count = 0
            
            # Get a list of expired payment hashes
            expired_hashes = []
            for payment_hash, entry in self.node._preimage_cache.items():
                if isinstance(entry, dict) and 'expiry' in entry:
                    if entry['expiry'] < now:
                        expired_hashes.append(payment_hash)
            
            # Remove expired entries
            for payment_hash in expired_hashes:
                del self.node._preimage_cache[payment_hash]
                expired_count += 1
                
            return expired_count

        for retry in range(MAX_RETRIES):
            try:
                logger.info(f"Starting asset transfer monitoring (attempt {retry + 1}/{MAX_RETRIES})")

                # Start heartbeat task
                heartbeat_task = asyncio.create_task(log_heartbeat())

                # Subscribe to send events
                request = taprootassets_pb2.SubscribeSendEventsRequest()
                
                try:
                    send_events = self.node.stub.SubscribeSendEvents(request)
                    logger.info("Successfully subscribed to send events")
                except Exception as e:
                    logger.error(f"Error creating subscription: {str(e)}")
                    raise

                # Process incoming events
                async for event in send_events:
                    logger.debug("Received send event")
                    # Asset transfer happens through the Lightning layer
                    # We only monitor these events for informational purposes

            except grpc.aio.AioRpcError as grpc_error:
                logger.error(f"gRPC error in subscription: {grpc_error.code()}: {grpc_error.details()}")

            except Exception as e:
                logger.error(f"Error in asset transfer monitoring: {str(e)}")

            finally:
                # Cancel heartbeat task
                if 'heartbeat_task' in locals():
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

            # Wait before retrying
            if retry < MAX_RETRIES - 1:
                logger.info(f"Retrying in {RETRY_DELAY} seconds")
                await asyncio.sleep(RETRY_DELAY)

        logger.warning("Max retries reached for monitoring")
        
        # Reset monitoring state to allow future attempts
        TaprootTransferManager._is_monitoring = False
        
        # Create a new monitoring task
        asyncio.create_task(self.monitor_asset_transfers())

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
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"Failed to settle internal payment: {payment_hash}, error: {error_msg}")
                    
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
                    script_key_hex = await self._extract_script_key_from_invoice(invoice)
                    
                    if script_key_hex:
                        self.node.invoice_manager._store_script_key_mapping(script_key_hex, payment_hash)
                    
                    # Get wallet info if available
                    user_id = None
                    wallet_id = None
                    if hasattr(self.node, 'wallet') and self.node.wallet:
                        user_id = self.node.wallet.user
                        wallet_id = self.node.wallet.id
                    
                    # Attempt settlement using Settlement Service
                    success, result = await SettlementService.settle_invoice(
                        payment_hash=payment_hash,
                        node=self.node,
                        is_internal=False,
                        is_self_payment=False,
                        user_id=user_id,
                        wallet_id=wallet_id
                    )
                    
                    if not success:
                        error_msg = result.get('error', 'Unknown error')
                        logger.error(f"Failed to settle Lightning payment: {payment_hash}, error: {error_msg}")
                    
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
            logger.error(f"Error monitoring invoice: {str(e)}")

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
                    logger.error(f"Error extracting script key: {str(e)}")
        
        return None
