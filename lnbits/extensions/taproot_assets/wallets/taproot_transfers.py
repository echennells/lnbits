# /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/wallets/taproot_transfers.py
import asyncio
import hashlib
from typing import Optional
import grpc
import grpc.aio
from loguru import logger

from .taproot_adapter import (
    taprootassets_pb2,
    invoices_pb2
)

# Import database functions
from ..crud import get_invoice_by_payment_hash, update_invoice_status

# Add version marker to verify code deployment
VERSION = "v4.0 - Fixed Main Path"
logger.info(f"=== LOADING TAPROOT TRANSFERS MODULE {VERSION} ===")

# Module-level direct settlement function
async def direct_settle_invoice(node, payment_hash):
    """
    Direct settlement function at module level to bypass any method overriding.
    """
    logger.info(f"🔴 DIRECT SETTLEMENT FUNCTION CALLED FOR {payment_hash} 🔴")

    try:
        # Get the preimage for this payment hash
        preimage_hex = node._get_preimage(payment_hash)

        if not preimage_hex:
            logger.error(f"❌ No preimage found for payment hash {payment_hash}")
            logger.info(f"Available payment hashes in cache: {list(node._preimage_cache.keys())}")
            return False

        logger.info(f"✅ Found preimage: {preimage_hex[:6]}...{preimage_hex[-6:]}")

        # Convert the preimage to bytes
        preimage_bytes = bytes.fromhex(preimage_hex)

        # Validate preimage length
        if len(preimage_bytes) != 32:
            logger.error(f"❌ Invalid preimage length: {len(preimage_bytes)}, expected 32 bytes")
            return False

        # Create settlement request
        logger.info("⏳ Creating SettleInvoice request")
        settle_request = invoices_pb2.SettleInvoiceMsg(
            preimage=preimage_bytes
        )

        # Settle the invoice
        logger.info("🚀 Calling SettleInvoice RPC DIRECTLY...")
        await node.invoices_stub.SettleInvoice(settle_request)
        logger.info(f"💥 INVOICE {payment_hash} SUCCESSFULLY SETTLED 💥")

        # Update the invoice status in the database
        try:
            # Look up the invoice by payment hash
            logger.info(f"Looking up invoice in database by payment_hash: {payment_hash}")
            invoice = await get_invoice_by_payment_hash(payment_hash)

            if invoice:
                logger.info(f"Found invoice with ID: {invoice.id}, updating status to 'paid'")
                
                # Debug log the invoice details before update
                logger.info(f"Invoice before update: status={invoice.status}, id={invoice.id}, payment_hash={invoice.payment_hash}")
                
                # Update the invoice status to "paid"
                updated_invoice = await update_invoice_status(invoice.id, "paid")
                
                # Add extra verification
                if updated_invoice:
                    logger.info(f"✅ Database updated: Invoice {invoice.id} status set to '{updated_invoice.status}'")
                    if updated_invoice.status != "paid":
                        logger.error(f"❌ Invoice status was not changed to 'paid'! Current status: {updated_invoice.status}")
                    if updated_invoice.paid_at is None:
                        logger.error(f"❌ Invoice paid_at timestamp was not set!")
                else:
                    logger.error(f"❌ Failed to update invoice status - update_invoice_status returned None")
                
                # Double-check that the invoice was updated
                verification_invoice = await get_invoice_by_payment_hash(payment_hash)
                if verification_invoice and verification_invoice.status == "paid":
                    logger.info(f"✓ Verified invoice status is now 'paid' in database")
                else:
                    logger.error(f"❌ Verification failed! Invoice status is not 'paid' in database")
                    if verification_invoice:
                        logger.error(f"   Current status: {verification_invoice.status}")
            else:
                logger.warning(f"⚠️ No invoice found in database with payment_hash: {payment_hash}")
        except Exception as db_error:
            logger.error(f"❌ Error updating invoice status in database: {db_error}", exc_info=True)
            # Continue even if database update fails - the invoice is still settled at the blockchain level

        return True

    except Exception as e:
        logger.error(f"❌ Failed to settle invoice: {e}", exc_info=True)
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
        # Log version on initialization to verify instance creation
        logger.info(f"TaprootTransferManager initialized - {VERSION}")

    async def monitor_asset_transfers(self):
        """
        Monitor asset transfers and settle HODL invoices when transfers complete.
        """
        logger.info(f"=== MONITOR_ASSET_TRANSFERS FUNCTION STARTED - {VERSION} ===")
        logger.info("This function should be called when TaprootAssetsNodeExtension is initialized")

        RETRY_DELAY = 5  # seconds
        MAX_RETRIES = 3  # number of retries before giving up
        HEARTBEAT_INTERVAL = 10  # seconds - reduced for more frequent heartbeats

        async def log_heartbeat():
            """Log periodic heartbeat to confirm subscription is active"""
            counter = 0
            while True:
                try:
                    counter += 1
                    logger.info(f"Asset transfer monitoring heartbeat #{counter} - subscription active - {VERSION}")

                    # Check for unprocessed payments on every heartbeat
                    script_key_mappings = list(self.node.invoice_manager._script_key_to_payment_hash.keys())
                    if script_key_mappings:
                        logger.info(f"Current script key mappings:")
                        for script_key in script_key_mappings:
                            payment_hash = self.node.invoice_manager._script_key_to_payment_hash.get(script_key)
                            logger.info(f"  - Script key: {script_key[:6]}...{script_key[-6:]} -> Payment hash: {payment_hash[:6]}...{payment_hash[-6:]}")
                            # If we find a script key with payment hash, try to settle immediately
                            if payment_hash and payment_hash in self.node._preimage_cache:
                                logger.info(f"🚨 Found unprocessed payment in heartbeat! Attempting immediate settlement...")
                                settlement_result = await direct_settle_invoice(self.node, payment_hash)
                                if settlement_result:
                                    logger.info(f"💯 Heartbeat settlement successful for {payment_hash}")

                                    # Also directly update the database
                                    try:
                                        # Look up the invoice by payment hash
                                        logger.info(f"Looking up invoice in database by payment_hash: {payment_hash}")
                                        invoice_db = await get_invoice_by_payment_hash(payment_hash)

                                        if invoice_db:
                                            logger.info(f"Found invoice with ID: {invoice_db.id}, updating status to 'paid'")
                                            # Update the invoice status to "paid"
                                            updated_invoice = await update_invoice_status(invoice_db.id, "paid")
                                            logger.info(f"✅ Database updated: Invoice {invoice_db.id} status set to 'paid'")
                                        else:
                                            logger.warning(f"⚠️ No invoice found in database with payment_hash: {payment_hash}")
                                    except Exception as db_error:
                                        logger.error(f"❌ Error updating invoice status in database: {db_error}", exc_info=True)
                                else:
                                    logger.error(f"❌ Heartbeat settlement failed for {payment_hash}")

                    else:
                        logger.info("No script key mappings available")

                    # Log preimage cache
                    logger.info(f"Current preimage cache size: {len(self.node._preimage_cache)}")
                    logger.info(f"Available payment hashes in cache: {list(self.node._preimage_cache.keys())}")

                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                except asyncio.CancelledError:
                    break

        for retry in range(MAX_RETRIES):
            try:
                logger.info(f"Starting asset transfer monitoring (attempt {retry + 1}/{MAX_RETRIES}) - {VERSION}")

                # Start heartbeat task
                heartbeat_task = asyncio.create_task(log_heartbeat())

                # Subscribe to send events from TAPD
                # This is kept for monitoring and debugging
                logger.info("=== STARTING SEND EVENTS SUBSCRIPTION ===")
                logger.info("Creating SubscribeSendEventsRequest")
                request = taprootassets_pb2.SubscribeSendEventsRequest()
                logger.info(f"Subscribing to send events with request: {request}")

                # Create the subscription
                logger.info("About to call self.node.stub.SubscribeSendEvents")
                try:
                    send_events = self.node.stub.SubscribeSendEvents(request)
                    logger.info(f"SubscribeSendEvents returned: {type(send_events)}")
                    logger.info("Successfully subscribed to send events")
                    logger.info("Waiting for send events...")
                except Exception as e:
                    logger.error(f"Error creating subscription: {e}", exc_info=True)
                    raise

                # Counter for events received
                event_counter = 0

                # Process incoming events
                async for event in send_events:
                    try:
                        event_counter += 1
                        # Log detailed event information
                        logger.info(f"=== RECEIVED SEND EVENT #{event_counter} ===")
                        logger.info(f"Event type: {type(event)}")

                        # We don't take action based on send events since the asset
                        # transfer happens through the Lightning layer
                        logger.info("Asset transfer events are informational only - no action needed")

                    except Exception as event_error:
                        logger.error(f"Error processing send event: {event_error}", exc_info=True)
                        continue

            except grpc.aio.AioRpcError as grpc_error:
                logger.error(f"gRPC error in send events subscription: {grpc_error.code()}: {grpc_error.details()}")
                if hasattr(grpc_error, 'debug_error_string'):
                    logger.error(f"gRPC debug info: {grpc_error.debug_error_string()}")

            except Exception as e:
                logger.error(f"Error in asset transfer monitoring: {e}", exc_info=True)

            finally:
                # Cancel heartbeat task
                if 'heartbeat_task' in locals():
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

            # If we reach here, the subscription has ended - wait before retrying
            if retry < MAX_RETRIES - 1:  # Don't sleep on the last retry
                logger.info(f"Retrying asset transfer monitoring in {RETRY_DELAY} seconds...")
                await asyncio.sleep(RETRY_DELAY)

        logger.error("Max retries reached for asset transfer monitoring")
        logger.info("Restarting asset transfer monitoring...")
        # Create a new monitoring task to ensure we don't stop monitoring completely
        new_task = asyncio.create_task(self.monitor_asset_transfers())
        logger.info(f"Created new monitoring task: {new_task}")

    async def monitor_invoice(self, payment_hash: str):
        """
        Monitor a specific invoice for state changes.
        DIRECT IMPLEMENTATION OF THE SETTLEMENT LOGIC TO FIX MAIN PATH.
        """
        logger.info(f"🌟 DIRECT IMPLEMENTATION monitor_invoice for {payment_hash} - {VERSION} 🌟")

        try:
            # Convert payment hash to bytes
            payment_hash_bytes = bytes.fromhex(payment_hash) if isinstance(payment_hash, str) else payment_hash
            request = invoices_pb2.SubscribeSingleInvoiceRequest(r_hash=payment_hash_bytes)

            # Subscribe to invoice updates
            async for invoice in self.node.invoices_stub.SubscribeSingleInvoice(request):
                try:
                    # Map state to human-readable form
                    state_map = {0: "OPEN", 1: "SETTLED", 2: "CANCELED", 3: "ACCEPTED"}
                    state_name = state_map.get(invoice.state, f"UNKNOWN({invoice.state})")
                    logger.info(f"Invoice update: {payment_hash}, State: {state_name}")

                    # Check if the invoice is in the ACCEPTED state
                    if invoice.state == 3:  # ACCEPTED state
                        logger.info(f"🔔 Invoice {payment_hash} is ACCEPTED (state=3) - DIRECT MAIN PATH - {VERSION}")

                        # Process HTLCs
                        script_key_found = False
                        asset_id = None
                        asset_amount = None
                        script_key_hex = None

                        if hasattr(invoice, 'htlcs') and invoice.htlcs:
                            logger.info(f"Found {len(invoice.htlcs)} HTLCs")

                            for htlc in invoice.htlcs:
                                if hasattr(htlc, 'custom_records') and htlc.custom_records:
                                    records = htlc.custom_records

                                    # Process record 65543 (asset transfer with script key)
                                    if 65543 in records and isinstance(records[65543], bytes):
                                        value = records[65543]
                                        logger.info(f"Processing asset transfer record (65543), length: {len(value)} bytes")
                                        # Log raw data for debugging
                                        logger.info(f"Raw record 65543 data: {value.hex()}")

                                        try:
                                            # Extract asset ID
                                            asset_id_marker = b'\x00\x20'
                                            asset_id_pos = value.find(asset_id_marker)
                                            if asset_id_pos >= 0:
                                                asset_id_start = asset_id_pos + 2
                                                asset_id_end = asset_id_start + 32
                                                asset_id_bytes = value[asset_id_start:asset_id_end]
                                                asset_id = asset_id_bytes.hex()
                                                logger.info(f"Found asset ID marker at position {asset_id_pos}, extracted ID: {asset_id}")

                                                # Extract script key
                                                script_key_marker = b'\x01\x40'
                                                script_key_pos = value.find(script_key_marker, asset_id_end)
                                                if script_key_pos >= 0:
                                                    logger.info(f"Found script key marker at position {script_key_pos}")
                                                    script_key_start = script_key_pos + 2
                                                    script_key_end = script_key_start + 33
                                                    script_key = value[script_key_start:script_key_end]
                                                    script_key_hex = script_key.hex()

                                                    # Store mapping
                                                    self.node.invoice_manager._store_script_key_mapping(script_key_hex, payment_hash)
                                                    logger.info(f"Stored script key mapping: {script_key_hex} -> {payment_hash}")
                                                    script_key_found = True
                                        except Exception as e:
                                            logger.error(f"Error extracting script key: {e}")

                                    # Process record 65536 (asset ID and amount)
                                    if 65536 in records and isinstance(records[65536], bytes):
                                        value = records[65536]
                                        logger.info(f"Processing asset info record (65536), length: {len(value)} bytes")
                                        # Log raw data for debugging
                                        logger.info(f"Raw record 65536 data: {value.hex()}")

                                        try:
                                            # Extract asset ID
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
                                                    logger.info(f"Extracted asset ID: {asset_id}, amount: {asset_amount}")
                                        except Exception as e:
                                            logger.error(f"Error processing asset info: {e}")

                        # Fallback mapping if no script key found
                        if not script_key_found:
                            self.node.invoice_manager._store_script_key_mapping(payment_hash, payment_hash)
                            logger.info(f"No script key found, stored self-mapping for payment hash: {payment_hash}")

                        # Debug values
                        logger.info(f"Extracted values - script_key_found: {script_key_found}, asset_id: {asset_id}, asset_amount: {asset_amount}")

                        # Process asset transfer and then settle invoice
                        if script_key_found and asset_id and asset_amount:
                            try:
                                logger.info(f"🔍 Starting asset transfer verification process")
                                logger.info(f"Script key found: {script_key_found}, Asset ID: {asset_id}, Amount: {asset_amount}")
                                logger.info(f"Initiating asset transfer - ID: {asset_id}, Script Key: {script_key_hex}, Amount: {asset_amount}")

                                # Verify asset transfer
                                try:
                                    logger.info("🚀 Attempting direct transfer and settlement")
                                    logger.info(f"Transfer parameters - Asset ID: {asset_id}, Script Key: {script_key_hex}, Amount: {asset_amount}")

                                    # Call node's asset_manager.send_asset which now just verifies the transfer
                                    transfer_result = await self.node.asset_manager.send_asset(
                                        asset_id=asset_id,
                                        script_key=script_key_hex,
                                        amount=asset_amount
                                    )
                                    logger.info(f"✅ Transfer verification result: {transfer_result}")
                                    logger.info("Asset transfer initiated successfully")

                                    # CRITICAL CHANGE: Call direct_settle_invoice function directly after verification
                                    logger.info("💫 Proceeding to direct settlement...")
                                    logger.info("⚡⚡⚡ IMMEDIATE SETTLEMENT IN MAIN PATH ⚡⚡⚡")
                                    settlement_result = await direct_settle_invoice(self.node, payment_hash)
                                    logger.info(f"🎯 Direct settlement attempt result: {settlement_result}")

                                    # Check post-settlement state
                                    logger.info("📊 Post-settlement state check:")
                                    logger.info(f"Preimage cache status: {list(self.node._preimage_cache.keys())}")
                                    logger.info(f"Script key mappings: {self.node.invoice_manager._script_key_to_payment_hash}")

                                except Exception as e:
                                    logger.error(f"❌ Error in transfer/settlement process: {e}", exc_info=True)
                            except Exception as e:
                                logger.error(f"Failed to initiate asset transfer: {e}", exc_info=True)
                        else:
                            logger.warning(f"Cannot initiate asset transfer: missing required information")

                        logger.info("Continuing to monitor invoice state changes (fallback path)")

                    elif invoice.state == 1:  # SETTLED state
                        logger.info(f"Invoice {payment_hash} is SETTLED")

                        # Update the invoice status in the database
                        try:
                            # Look up the invoice by payment hash
                            logger.info(f"Looking up invoice in database by payment_hash: {payment_hash}")
                            invoice_db = await get_invoice_by_payment_hash(payment_hash)

                            if invoice_db:
                                logger.info(f"Found invoice with ID: {invoice_db.id}, updating status to 'paid'")
                                # Update the invoice status to "paid"
                                updated_invoice = await update_invoice_status(invoice_db.id, "paid")
                                logger.info(f"✅ Database updated: Invoice {invoice_db.id} status set to 'paid'")
                            else:
                                logger.warning(f"⚠️ No invoice found in database with payment_hash: {payment_hash}")
                        except Exception as db_error:
                            logger.error(f"❌ Error updating invoice status in database: {db_error}", exc_info=True)

                        break
                    elif invoice.state == 2:  # CANCELED state
                        logger.warning(f"Invoice {payment_hash} was CANCELED")
                        break

                except Exception as e:
                    logger.error(f"Error processing invoice update: {e}", exc_info=True)
                    continue

        except Exception as e:
            logger.error(f"Error monitoring invoice {payment_hash}: {e}", exc_info=True)

    async def settle_invoice_with_preimage(self, payment_hash: str):
        """
        Settle an invoice using the stored preimage.

        Args:
            payment_hash: The payment hash of the invoice to settle

        Returns:
            bool: True if settlement was successful, False otherwise
        """
        logger.info(f"=== SETTLING INVOICE via settle_invoice_with_preimage - {VERSION} ===")
        return await direct_settle_invoice(self.node, payment_hash)

    async def manually_settle_invoice(self, payment_hash: str, script_key: Optional[str] = None):
        """
        Manually settle a HODL invoice using the stored preimage.
        This can be used as a fallback if automatic settlement fails.

        Args:
            payment_hash: The payment hash of the invoice to settle
            script_key: Optional script key to use for lookup if payment hash is not found directly

        Returns:
            bool: True if settlement was successful, False otherwise
        """
        logger.info(f"=== MANUAL SETTLEMENT ATTEMPT - {VERSION} ===")
        logger.info(f"Payment hash: {payment_hash}")
        if script_key:
            logger.info(f"Script key: {script_key}")

        try:
            # Try to get the preimage directly from the payment hash
            preimage_hex = self.node._get_preimage(payment_hash)

            # If not found and script key is provided, try to look up the payment hash
            if not preimage_hex and script_key:
                logger.info(f"Preimage not found directly, trying script key lookup")
                mapped_payment_hash = self.node.invoice_manager._get_payment_hash_from_script_key(script_key)
                if mapped_payment_hash:
                    logger.info(f"Found payment hash via script key: {mapped_payment_hash}")
                    preimage_hex = self.node._get_preimage(mapped_payment_hash)

            # Use the direct settle function
            if preimage_hex:
                return await direct_settle_invoice(self.node, payment_hash)
            else:
                logger.error(f"No preimage found for payment hash {payment_hash}")
                logger.info(f"Available payment hashes in cache: {list(self.node._preimage_cache.keys())}")
                logger.info(f"Available script key mappings: {list(self.node.invoice_manager._script_key_to_payment_hash.keys())}")
                return False

        except Exception as e:
            logger.error(f"Failed to manually settle invoice: {e}", exc_info=True)
            return False
