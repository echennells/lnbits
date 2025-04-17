import asyncio
import hashlib
from typing import Optional, Tuple, Any, Dict
import grpc
import grpc.aio
from loguru import logger

from .taproot_adapter import (
    taprootassets_pb2,
    invoices_pb2
)

# Import database functions
from ..crud import get_invoice_by_payment_hash, update_invoice_status

# Module-level direct settlement function
async def direct_settle_invoice(node, payment_hash: str) -> bool:
    """
    Settle an invoice directly using the stored preimage.
    
    Args:
        node: The node instance
        payment_hash: The payment hash of the invoice to settle
        
    Returns:
        bool: True if settled successfully, False otherwise
    """
    logger.info(f"Settling invoice for payment hash {payment_hash}")

    try:
        # Get the preimage for this payment hash
        preimage_hex = node._get_preimage(payment_hash)

        if not preimage_hex:
            logger.error(f"No preimage found for payment hash {payment_hash}")
            return False

        # Convert the preimage to bytes
        preimage_bytes = bytes.fromhex(preimage_hex)

        # Create settlement request
        settle_request = invoices_pb2.SettleInvoiceMsg(
            preimage=preimage_bytes
        )

        # Settle the invoice
        await node.invoices_stub.SettleInvoice(settle_request)
        logger.info(f"Invoice {payment_hash} successfully settled")

        # Update the invoice status in the database
        try:
            invoice = await get_invoice_by_payment_hash(payment_hash)

            if invoice:
                updated_invoice = await update_invoice_status(invoice.id, "paid")
                if updated_invoice and updated_invoice.status == "paid":
                    logger.info(f"Database updated: Invoice {invoice.id} status set to paid")
                else:
                    logger.error(f"Failed to update invoice status in database")
            else:
                logger.warning(f"No invoice found with payment_hash: {payment_hash}")
        except Exception as db_error:
            logger.error(f"Error updating invoice status: {str(db_error)}")
            # Continue even if DB update fails - the important part is settlement

        return True

    except Exception as e:
        logger.error(f"Failed to settle invoice: {str(e)}")
        return False


class TaprootTransferManager:
    """
    Handles Taproot Asset transfer monitoring.
    This class is responsible for monitoring asset transfers and settling HODL invoices.
    """

    def __init__(self, node):
        """
        Initialize the transfer manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node
        self.is_monitoring = False
        logger.info("TaprootTransferManager initialized")

    async def monitor_asset_transfers(self):
        """
        Monitor asset transfers and settle HODL invoices when transfers complete.
        """
        if self.is_monitoring:
            logger.info("Monitoring already active, ignoring duplicate call")
            return
            
        self.is_monitoring = True
        logger.info("Starting asset transfer monitoring")

        RETRY_DELAY = 5  # seconds
        MAX_RETRIES = 3  # number of retries before giving up
        HEARTBEAT_INTERVAL = 30  # seconds

        async def check_unprocessed_payments():
            """Check for any unprocessed payments and attempt to settle them."""
            # Get all script key mappings
            script_key_mappings = list(self.node.invoice_manager._script_key_to_payment_hash.keys())
            if not script_key_mappings:
                return
                
            for script_key in script_key_mappings:
                payment_hash = self.node.invoice_manager._get_payment_hash_from_script_key(script_key)
                if payment_hash and payment_hash in self.node._preimage_cache:
                    logger.info(f"Found unprocessed payment, attempting settlement")
                    await direct_settle_invoice(self.node, payment_hash)

        async def log_heartbeat():
            """Log periodic heartbeat and check for unprocessed payments."""
            counter = 0
            while True:
                try:
                    counter += 1
                    logger.debug(f"Transfer monitoring heartbeat #{counter}")
                    
                    # Check for unprocessed payments
                    await check_unprocessed_payments()
                    
                    # Log cache size if not empty
                    cache_size = len(self.node._preimage_cache)
                    if cache_size > 0:
                        logger.info(f"Preimage cache size: {cache_size}")

                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                except asyncio.CancelledError:
                    break

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
                    # We only monitor these events for informational purposes
                    # The actual settlement happens through HODL invoice mechanisms

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
        self.is_monitoring = False
        
        # Create a new monitoring task
        asyncio.create_task(self.monitor_asset_transfers())

    async def monitor_invoice(self, payment_hash: str):
        """
        Monitor a specific invoice for state changes.
        """
        logger.info(f"Monitoring invoice {payment_hash}")

        try:
            # Convert payment hash to bytes
            payment_hash_bytes = bytes.fromhex(payment_hash)
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
                    
                    # Attempt settlement
                    await direct_settle_invoice(self.node, payment_hash)
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

    async def manually_settle_invoice(self, payment_hash: str, script_key: Optional[str] = None) -> bool:
        """Manually settle a HODL invoice. Used as a fallback if automatic settlement fails."""
        logger.info(f"Manual settlement attempt for {payment_hash}")
        
        try:
            # Try to get the preimage directly from the payment hash
            preimage_hex = self.node._get_preimage(payment_hash)
            
            # If not found and script key is provided, try to look up the payment hash
            if not preimage_hex and script_key:
                mapped_payment_hash = self.node.invoice_manager._get_payment_hash_from_script_key(script_key)
                if mapped_payment_hash:
                    preimage_hex = self.node._get_preimage(mapped_payment_hash)
            
            # Use the direct settle function
            if preimage_hex:
                return await direct_settle_invoice(self.node, payment_hash)
            else:
                logger.error(f"No preimage found for {payment_hash}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to manually settle invoice: {str(e)}")
            return False
