import os
import time
import hashlib
import asyncio
from typing import Optional, Dict, Any
import grpc
import grpc.aio
from loguru import logger
from lnbits import bolt11

from .taproot_adapter import (
    taprootassets_pb2,
    rfq_pb2,
    rfq_pb2_grpc,
    tapchannel_pb2,
    lightning_pb2,
    invoices_pb2
)

class TaprootInvoiceManager:
    """Handles Taproot Asset invoice creation and monitoring."""

    def __init__(self, node):
        self.node = node
        self._script_key_to_payment_hash = {}

    def _store_script_key_mapping(self, script_key: str, payment_hash: str):
        self._script_key_to_payment_hash[script_key] = payment_hash
        logger.debug(f"Stored script key mapping: {script_key} -> {payment_hash}")

    def _get_payment_hash_from_script_key(self, script_key: str) -> Optional[str]:
        payment_hash = self._script_key_to_payment_hash.get(script_key)
        if not payment_hash:
            logger.debug(f"No payment hash found for script key {script_key}")
        return payment_hash

    async def create_asset_invoice(self, memo: str, asset_id: str, asset_amount: int,
                               expiry: Optional[int] = None, peer_pubkey: Optional[str] = None) -> Dict[str, Any]:
        """Create an invoice for a Taproot Asset transfer."""
        try:
            logger.info(f"Creating asset invoice for asset_id={asset_id}, amount={asset_amount}")

            # Convert parameters to expected types
            asset_id_bytes = bytes.fromhex(asset_id)
            expiry_time = int(time.time()) + (expiry or 3600)

            # Create buy order request
            rfq_stub = rfq_pb2_grpc.RfqStub(self.node.channel)
            buy_order_request = rfq_pb2.AddAssetBuyOrderRequest(
                asset_specifier=rfq_pb2.AssetSpecifier(asset_id=asset_id_bytes),
                asset_max_amt=asset_amount,
                expiry=expiry_time,
                timeout_seconds=30
            )

            # Add peer pubkey if provided
            if peer_pubkey:
                buy_order_request.peer_pub_key = bytes.fromhex(peer_pubkey)

            try:
                # Submit the buy order
                buy_order_response = await rfq_stub.AddAssetBuyOrder(buy_order_request, timeout=30)
            except grpc.aio.AioRpcError as e:
                logger.error(f"gRPC error in AddAssetBuyOrder: {e.code()}: {e.details()}")
                raise Exception(f"Failed to create buy order: {e.details()}")
            
            # Verify we got an accepted quote
            if not hasattr(buy_order_response, 'accepted_quote'):
                error_message = "No quote accepted for the asset"
                if hasattr(buy_order_response, 'invalid_quote'):
                    error_message = f"Invalid quote: {buy_order_response.invalid_quote.status}"
                elif hasattr(buy_order_response, 'rejected_quote'):
                    error_message = f"Quote rejected: {buy_order_response.rejected_quote.error_message}"
                raise Exception(error_message)
            
            # Extract quote information
            selected_quote = buy_order_response.accepted_quote
            quote_id = selected_quote.id.hex() if isinstance(selected_quote.id, bytes) else selected_quote.id
            logger.info(f"Quote accepted - ID: {quote_id}, SCID: {hex(selected_quote.scid)}")

            # Generate a preimage and payment hash
            preimage = os.urandom(32)
            preimage_hex = preimage.hex()
            payment_hash = hashlib.sha256(preimage).digest()
            payment_hash_hex = payment_hash.hex()
            logger.info(f"Generated payment_hash: {payment_hash_hex}")

            # Store the preimage for settlement
            self.node._store_preimage(payment_hash_hex, preimage_hex)

            # Create the invoice
            invoice = lightning_pb2.Invoice(
                memo=memo or "Taproot Asset Transfer",
                value=0,  # No Bitcoin value
                private=True,
                expiry=expiry or 3600
            )

            # Create HODL invoice
            hodl_invoice = tapchannel_pb2.HodlInvoice(
                payment_hash=payment_hash
            )

            # Create full invoice request
            request = tapchannel_pb2.AddInvoiceRequest(
                asset_id=asset_id_bytes,
                asset_amount=asset_amount
            )
            request.invoice_request.MergeFrom(invoice)
            request.hodl_invoice.MergeFrom(hodl_invoice)

            # Add peer pubkey if provided
            if peer_pubkey:
                request.peer_pubkey = bytes.fromhex(peer_pubkey)

            # Start monitoring the invoice for settlement
            logger.info(f"Starting invoice monitoring for {payment_hash_hex}")
            asyncio.create_task(self.node.monitor_invoice(payment_hash_hex))

            try:
                # Send invoice request to daemon
                response = await self.node.tapchannel_stub.AddInvoice(request, timeout=30)
            except grpc.aio.AioRpcError as e:
                logger.error(f"gRPC error in AddInvoice: {e.code()}: {e.details()}")
                raise Exception(f"Failed to add invoice: {e.details()}")
            
            # Extract and return payment details
            return {
                "accepted_buy_quote": self.node._protobuf_to_dict(response.accepted_buy_quote) 
                                     if hasattr(response, 'accepted_buy_quote') else {},
                "invoice_result": {
                    "r_hash": payment_hash_hex,
                    "payment_request": response.invoice_result.payment_request
                }
            }

        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC error in create_asset_invoice: {e.code()}: {e.details()}")
            raise Exception(f"gRPC error: {e.details()}")
        except Exception as e:
            logger.error(f"Failed to create asset invoice: {str(e)}", exc_info=True)
            raise Exception(f"Failed to create asset invoice: {str(e)}")

    async def monitor_invoice(self, payment_hash: str):
        """Monitor a specific invoice for state changes."""
        logger.info(f"Starting invoice monitoring for payment_hash={payment_hash}")

        try:
            # Convert payment hash to bytes
            payment_hash_bytes = bytes.fromhex(payment_hash) if isinstance(payment_hash, str) else payment_hash
            request = invoices_pb2.SubscribeSingleInvoiceRequest(r_hash=payment_hash_bytes)

            try:
                # Subscribe to invoice updates
                invoice_stream = self.node.invoices_stub.SubscribeSingleInvoice(request)
                async for invoice in invoice_stream:
                    # Map state to human-readable form
                    state_map = {0: "OPEN", 1: "SETTLED", 2: "CANCELED", 3: "ACCEPTED"}
                    state_name = state_map.get(invoice.state, f"UNKNOWN({invoice.state})")
                    logger.info(f"Invoice update: {payment_hash}, State: {state_name}")

                    # Handle ACCEPTED state
                    if invoice.state == 3:  # ACCEPTED state
                        logger.info(f"Invoice {payment_hash} is ACCEPTED (state=3)")
                        
                        # Process HTLCs to extract script key
                        script_key_hex = None
                        
                        if hasattr(invoice, 'htlcs') and invoice.htlcs:
                            for htlc in invoice.htlcs:
                                if hasattr(htlc, 'custom_records') and htlc.custom_records:
                                    # Process asset transfer record (65543)
                                    if 65543 in htlc.custom_records:
                                        value = htlc.custom_records[65543]
                                        script_key_hex = self._extract_script_key_from_record(value, payment_hash)
                        
                        # Store mapping and attempt settlement
                        if script_key_hex:
                            self._store_script_key_mapping(script_key_hex, payment_hash)
                            
                            # Delegate to transfer manager for settlement
                            from .taproot_transfers import direct_settle_invoice
                            await direct_settle_invoice(self.node, payment_hash)
                            break
                        else:
                            logger.warning(f"No script key found for {payment_hash}, trying fallback settlement")
                            from .taproot_transfers import direct_settle_invoice
                            await direct_settle_invoice(self.node, payment_hash)
                            break
                    
                    # Handle other terminal states
                    elif invoice.state == 1:  # SETTLED state
                        logger.info(f"Invoice {payment_hash} is already SETTLED")
                        break
                    elif invoice.state == 2:  # CANCELED state
                        logger.warning(f"Invoice {payment_hash} was CANCELED")
                        break
            except grpc.aio.AioRpcError as e:
                logger.error(f"gRPC error in SubscribeSingleInvoice: {e.code()}: {e.details()}")
                raise Exception(f"Failed to subscribe to invoice: {e.details()}")

        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC error in monitor_invoice: {e.code()}: {e.details()}")
        except Exception as e:
            logger.error(f"Error monitoring invoice {payment_hash}: {e}", exc_info=True)

    def _extract_script_key_from_record(self, record_value: bytes, payment_hash: str) -> Optional[str]:
        """Extract script key from the custom record data."""
        try:
            # Look for asset ID marker
            asset_id_marker = bytes.fromhex("0020")
            asset_id_pos = record_value.find(asset_id_marker)
            
            if asset_id_pos >= 0:
                # Find script key marker after asset ID
                asset_id_end = asset_id_pos + 2 + 32
                script_key_marker = bytes.fromhex("0140")
                script_key_pos = record_value.find(script_key_marker, asset_id_end)
                
                if script_key_pos >= 0:
                    script_key_start = script_key_pos + 2
                    script_key_end = script_key_start + 33  # Exactly 33 bytes
                    script_key = record_value[script_key_start:script_key_end]
                    return script_key.hex()
            
            return None
        except Exception as e:
            logger.error(f"Error extracting script key: {e}")
            return None
