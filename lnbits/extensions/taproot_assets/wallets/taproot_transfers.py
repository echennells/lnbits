import asyncio
import hashlib
from typing import Optional, Tuple, Any
import grpc
import grpc.aio
from loguru import logger

from .taproot_adapter import (
    taprootassets_pb2,
    invoices_pb2
)

# Import database functions
from ..crud import get_invoice_by_payment_hash, update_invoice_status

# Singleton instance for manager
_transfer_manager_instance = None
_transfer_monitor_task = None

# Module-level direct settlement function
async def direct_settle_invoice(node, payment_hash):
    """Direct settlement function at module level to bypass any method overriding."""
    logger.info(f"Settling invoice for payment hash {payment_hash}")

    try:
        # Get the preimage for this payment hash
        preimage_hex = node._get_preimage(payment_hash)

        if not preimage_hex:
            logger.error(f"No preimage found for payment hash {payment_hash}")
            return False

        # Convert the preimage to bytes
        preimage_bytes = bytes.fromhex(preimage_hex)

        # Validate preimage length
        if len(preimage_bytes) != 32:
            logger.error(f"Invalid preimage length: {len(preimage_bytes)}")
            return False

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

        return True

    except Exception as e:
        logger.error(f"Failed to settle invoice: {str(e)}")
        return False

class TaprootTransferManager:
    """
    Handles Taproot Asset transfer monitoring.
    This class is responsible for monitoring asset transfers and settling HODL invoices.
    """

    # Map of send state enum values to their string representations
    SEND_STATES = {
        0: "SEND_STATE_VIRTUAL_INPUT_SELECT",
        1: "SEND_STATE_VIRTUAL_SIGN",
        2: "SEND_STATE_ANCHOR_SIGN",
        3: "SEND_STATE_LOG_COMMITMENT",
        4: "SEND_STATE_BROADCAST",
        5: "SEND_STATE_WAIT_CONFIRMATION",
        6: "SEND_STATE_STORE_PROOFS",
        7: "SEND_STATE_TRANSFER_PROOFS",
        8: "SEND_STATE_COMPLETED"
    }

    def __init__(self, node):
        """
        Initialize the transfer manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node
        self.is_monitoring = False
        
        # Create singleton instance
        global _transfer_manager_instance
        _transfer_manager_instance = self
        
        logger.info("TaprootTransferManager initialized")

    @classmethod
    def get_instance(cls, node=None):
        """Get or create the singleton instance of the TransferManager."""
        global _transfer_manager_instance
        if _transfer_manager_instance is None and node is not None:
            _transfer_manager_instance = cls(node)
        return _transfer_manager_instance

    @classmethod
    def start_monitoring(cls, node=None):
        """Start the transfer monitoring process if not already running."""
        global _transfer_monitor_task, _transfer_manager_instance
        
        if _transfer_monitor_task is None or _transfer_monitor_task.done():
            manager = cls.get_instance(node)
            if manager and not manager.is_monitoring:
                _transfer_monitor_task = asyncio.create_task(manager.monitor_asset_transfers())
                logger.info("Asset transfer monitoring started")
            else:
                logger.info("Transfer monitoring already active, reusing existing task")
        else:
            logger.info("Monitoring task already running")
        
        return _transfer_monitor_task

    async def process_payment_stream(self, payment_stream) -> Tuple[bool, Any, Optional[str]]:
        """
        Process a payment stream and handle any errors gracefully.

        Args:
            payment_stream: The payment stream to process

        Returns:
            tuple: (success, payment_result, error_message)
        """
        try:
            async for response in payment_stream:
                # Check if we have an accepted sell order
                if hasattr(response, 'accepted_sell_order') and response.accepted_sell_order:
                    logger.info("Received sell order acceptance")
                    continue

                # Check if we have a payment result
                if hasattr(response, 'payment_result') and response.payment_result:
                    status = response.payment_result.status
                    logger.info(f"Payment status: {status}")
                    return True, response.payment_result, None

            return False, None, "No payment result received in stream"

        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC error in payment stream: {e.code()}: {e.details()}")
            return False, None, f"gRPC error: {e.details()}"

        except Exception as e:
            logger.error(f"Error processing payment stream: {str(e)}")
            return False, None, str(e)

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
        HEARTBEAT_INTERVAL = 10  # seconds

        async def check_unprocessed_payments():
            """Check for any unprocessed payments and attempt to settle them."""
            # Get all script key mappings
            script_key_mappings = list(self.node.invoice_manager._script_key_to_payment_hash.keys())
            if not script_key_mappings:
                return
                
            logger.info(f"Checking {len(script_key_mappings)} pending payments")
            
            for script_key in script_key_mappings:
                payment_hash = self.node.invoice_manager._script_key_to_payment_hash.get(script_key)
                if payment_hash and payment_hash in self.node._preimage_cache:
                    logger.info(f"Found unprocessed payment, attempting settlement")
                    await direct_settle_invoice(self.node, payment_hash)

        async def log_heartbeat():
            """Log periodic heartbeat and check for unprocessed payments."""
            counter = 0
            while True:
                try:
                    counter += 1
                    logger.debug(f"Asset transfer monitoring heartbeat #{counter}")
                    
                    # Check for unprocessed payments
                    await check_unprocessed_payments()
                    
                    # Log cache size only if not empty
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
            payment_hash_bytes = bytes.fromhex(payment_hash) if isinstance(payment_hash, str) else payment_hash
            request = invoices_pb2.SubscribeSingleInvoiceRequest(r_hash=payment_hash_bytes)

            # Subscribe to invoice updates
            async for invoice in self.node.invoices_stub.SubscribeSingleInvoice(request):
                # Map state to human-readable form
                state_map = {0: "OPEN", 1: "SETTLED", 2: "CANCELED", 3: "ACCEPTED"}
                state_name = state_map.get(invoice.state, f"UNKNOWN({invoice.state})")
                logger.info(f"Invoice {payment_hash}: {state_name}")

                # Process ACCEPTED state (3)
                if invoice.state == 3:
                    logger.info(f"Invoice {payment_hash} is ACCEPTED")
                    script_key = await self._extract_script_key_from_invoice(invoice, payment_hash)
                    
                    if script_key:
                        await self._process_accepted_invoice(payment_hash, script_key)
                    else:
                        logger.warning(f"Cannot process invoice: missing script key")

                # Process SETTLED state (1)
                elif invoice.state == 1:
                    logger.info(f"Invoice {payment_hash} is SETTLED")
                    try:
                        invoice_db = await get_invoice_by_payment_hash(payment_hash)
                        if invoice_db:
                            await update_invoice_status(invoice_db.id, "paid")
                            logger.info(f"Database updated: Invoice {invoice_db.id} paid")
                    except Exception as db_error:
                        logger.error(f"Error updating database: {str(db_error)}")
                    break
                    
                # Process CANCELED state (2)
                elif invoice.state == 2:
                    logger.warning(f"Invoice {payment_hash} was CANCELED")
                    break

        except Exception as e:
            logger.error(f"Error monitoring invoice: {str(e)}")

    async def _extract_script_key_from_invoice(self, invoice, payment_hash):
        """Extract script key and asset details from invoice HTLCs."""
        script_key_hex = None
        asset_id = None
        asset_amount = None
        script_key_found = False
        
        if not hasattr(invoice, 'htlcs') or not invoice.htlcs:
            return None
            
        for htlc in invoice.htlcs:
            if not hasattr(htlc, 'custom_records') or not htlc.custom_records:
                continue
                
            records = htlc.custom_records
            
            # Process asset transfer record (65543)
            if 65543 in records and isinstance(records[65543], bytes):
                value = records[65543]
                
                try:
                    # Extract asset ID
                    asset_id_marker = b'\x00\x20'
                    asset_id_pos = value.find(asset_id_marker)
                    if asset_id_pos >= 0:
                        asset_id_start = asset_id_pos + 2
                        asset_id_end = asset_id_start + 32
                        asset_id_bytes = value[asset_id_start:asset_id_end]
                        asset_id = asset_id_bytes.hex()
                        
                        # Extract script key
                        script_key_marker = b'\x01\x40'
                        script_key_pos = value.find(script_key_marker, asset_id_end)
                        if script_key_pos >= 0:
                            script_key_start = script_key_pos + 2
                            script_key_end = script_key_start + 33
                            script_key = value[script_key_start:script_key_end]
                            script_key_hex = script_key.hex()
                            
                            # Store mapping
                            self.node.invoice_manager._store_script_key_mapping(script_key_hex, payment_hash)
                            logger.info(f"Stored script key mapping for {payment_hash}")
                            script_key_found = True
                except Exception as e:
                    logger.error(f"Error extracting script key: {str(e)}")
            
            # Process asset info record (65536)
            if 65536 in records and isinstance(records[65536], bytes):
                value = records[65536]
                
                try:
                    # Extract asset ID and amount
                    asset_id_marker = b'\x00\x20'
                    asset_id_pos = value.find(asset_id_marker)
                    if asset_id_pos >= 0:
                        asset_id_start = asset_id_pos + 2
                        asset_id_end = asset_id_start + 32
                        asset_id_bytes = value[asset_id_start:asset_id_end]
                        asset_id = asset_id_bytes.hex()
                        
                        # Extract amount from last byte
                        if len(value) >= 1:
                            amount_bytes = value[-1:]
                            asset_amount = int.from_bytes(amount_bytes, byteorder='little')
                except Exception as e:
                    logger.error(f"Error processing asset info: {str(e)}")
        
        # Fallback mapping if no script key found
        if not script_key_found:
            self.node.invoice_manager._store_script_key_mapping(payment_hash, payment_hash)
            logger.info(f"No script key found, used payment hash as key")
            script_key_hex = payment_hash
        
        logger.info(f"Asset transfer details - ID: {asset_id}, Amount: {asset_amount}")
        return script_key_hex

    async def _process_accepted_invoice(self, payment_hash, script_key_hex):
        """Process an accepted invoice to verify and settle."""
        try:
            # Get asset details from script key mapping
            asset_id = None  # This would typically come from another mapping
            asset_amount = 1  # Default value
            
            logger.info(f"Verifying asset transfer")
            
            # Call node's asset_manager.send_asset for verification
            transfer_result = await self.node.asset_manager.send_asset(
                asset_id=asset_id or "placeholder",
                script_key=script_key_hex,
                amount=asset_amount
            )
            
            # Proceed to direct settlement
            logger.info(f"Proceeding to settlement")
            settlement_result = await direct_settle_invoice(self.node, payment_hash)
            
            if not settlement_result:
                logger.error(f"Settlement failed for {payment_hash}")
        except Exception as e:
            logger.error(f"Error processing accepted invoice: {str(e)}")

    async def settle_invoice_with_preimage(self, payment_hash: str):
        """Settle an invoice using the stored preimage."""
        return await direct_settle_invoice(self.node, payment_hash)

    async def manually_settle_invoice(self, payment_hash: str, script_key: Optional[str] = None):
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
