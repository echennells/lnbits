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
            logger.info(f"Starting asset invoice creation for asset_id={asset_id}, amount={asset_amount}")

            # Get channel assets
            channel_assets = await self.node.asset_manager.list_channel_assets()
            asset_channels = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
            logger.info(f"Found {len(asset_channels)} channels for asset_id={asset_id}")
            
            # Create RFQ client and process buy order
            rfq_stub = rfq_pb2_grpc.RfqStub(self.node.channel)
            selected_quote = None

            try:
                # Create buy order request
                asset_id_bytes = bytes.fromhex(asset_id)
                expiry = int(time.time()) + 3600
                buy_order_request = rfq_pb2.AddAssetBuyOrderRequest(
                    asset_specifier=rfq_pb2.AssetSpecifier(asset_id=asset_id_bytes),
                    asset_max_amt=asset_amount,
                    expiry=expiry,
                    timeout_seconds=30
                )
                if peer_pubkey:
                    buy_order_request.peer_pub_key = bytes.fromhex(peer_pubkey)

                # Send the buy order request
                buy_order_response = await rfq_stub.AddAssetBuyOrder(buy_order_request, timeout=30)
                logger.info("Successfully sent buy order request")

                # Handle the response
                if buy_order_response.HasField('accepted_quote'):
                    selected_quote = buy_order_response.accepted_quote
                    quote_id = selected_quote.id.hex() if isinstance(selected_quote.id, bytes) else selected_quote.id
                    quote_scid = selected_quote.scid
                    quote_scid_hex = quote_scid.hex() if isinstance(quote_scid, bytes) else hex(quote_scid) if isinstance(quote_scid, int) else str(quote_scid)
                    logger.info(f"Quote accepted - ID: {quote_id}, SCID: {quote_scid}, SCID (hex): {quote_scid_hex}")
                elif buy_order_response.HasField('invalid_quote'):
                    raise Exception(f"Buy order invalid: {buy_order_response.invalid_quote.status}")
                elif buy_order_response.HasField('rejected_quote'):
                    raise Exception(f"Buy order rejected: {buy_order_response.rejected_quote.error_message}")
            except Exception as e:
                logger.error(f"Error in buy order process: {str(e)}")
                raise

            if not selected_quote:
                raise Exception("Failed to obtain a valid quote for the asset")

            # Create the invoice request
            try:
                # Convert asset_id from hex to bytes
                asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id

                # Create standard invoice
                invoice = lightning_pb2.Invoice(
                    memo=memo if memo else "Taproot Asset Transfer",
                    value=0,
                    private=True,
                    expiry=300
                )

                # Add route hints using the quote's SCID
                tap_rfq_scid = selected_quote.scid
                logger.info(f"Using tap_rfq_scid={tap_rfq_scid} for route hints")

                # Convert peer ID to bytes
                if isinstance(selected_quote.peer, bytes):
                    peer_id_bytes = selected_quote.peer
                else:
                    peer_id_str = selected_quote.peer if isinstance(selected_quote.peer, str) else selected_quote.peer.hex()
                    peer_id_bytes = bytes.fromhex(peer_id_str)

                # Convert SCID to integer
                if isinstance(tap_rfq_scid, bytes):
                    scid_int = int.from_bytes(tap_rfq_scid, byteorder='little')
                elif isinstance(tap_rfq_scid, str) and all(c in '0123456789abcdef' for c in tap_rfq_scid.lower().replace('0x', '')):
                    scid_bytes = bytes.fromhex(tap_rfq_scid.lower().replace('0x', '').zfill(16))
                    scid_int = int.from_bytes(scid_bytes, byteorder='little')
                elif isinstance(tap_rfq_scid, str):
                    scid_int = int(tap_rfq_scid)
                elif isinstance(tap_rfq_scid, int):
                    scid_int = tap_rfq_scid
                else:
                    raise ValueError(f"Unexpected SCID type: {type(tap_rfq_scid)}")

                # Create hop hint
                hop_hint = lightning_pb2.HopHint(
                    node_id=peer_id_bytes.hex(),
                    chan_id=scid_int,
                    fee_base_msat=0,
                    fee_proportional_millionths=0,
                    cltv_expiry_delta=40
                )

                # Add route hint to invoice
                route_hint = lightning_pb2.RouteHint()
                route_hint.hop_hints.append(hop_hint)
                invoice.route_hints.append(route_hint)
                logger.info(f"Added route hint with node_id: {hop_hint.node_id}, chan_id: {hop_hint.chan_id}")

                # Generate preimage and payment hash
                preimage = os.urandom(32)
                preimage_hex = preimage.hex()
                payment_hash = hashlib.sha256(preimage).digest()
                payment_hash_hex = payment_hash.hex()
                logger.info(f"Generated payment_hash: {payment_hash_hex}")

                # Create HODL invoice
                hodl_invoice = tapchannel_pb2.HodlInvoice(payment_hash=payment_hash)

                # Create the full request
                request = tapchannel_pb2.AddInvoiceRequest(
                    asset_id=asset_id_bytes,
                    asset_amount=asset_amount
                )
                request.invoice_request.MergeFrom(invoice)
                request.hodl_invoice.MergeFrom(hodl_invoice)

                # Store preimage mapping
                self.node._store_preimage(payment_hash_hex, preimage_hex)
                logger.info(f"Stored preimage for payment_hash: {payment_hash_hex}")

                # Start monitoring using the transfer_manager's implementation
                # which includes direct settlement logic
                logger.info(f"🔄 Starting invoice monitoring with transfer_manager for {payment_hash_hex}")
                asyncio.create_task(self.node.monitor_invoice(payment_hash_hex))

                # Add peer_pubkey if provided
                if peer_pubkey:
                    request.peer_pubkey = bytes.fromhex(peer_pubkey)
                elif hasattr(selected_quote, 'peer'):
                    peer_bytes = selected_quote.peer if isinstance(selected_quote.peer, bytes) else bytes.fromhex(
                        selected_quote.peer if isinstance(selected_quote.peer, str) else selected_quote.peer.hex())
                    request.peer_pubkey = peer_bytes

                # Call AddInvoice
                logger.info("Calling TaprootAssetChannels.AddInvoice")
                response = await self.node.tapchannel_stub.AddInvoice(request, timeout=30)
                logger.info("Successfully received response from AddInvoice")

                # Extract payment details
                payment_hash = response.invoice_result.r_hash.hex() if isinstance(response.invoice_result.r_hash, bytes) else response.invoice_result.r_hash
                payment_request = response.invoice_result.payment_request

                # Convert accepted_buy_quote to dictionary
                accepted_buy_quote = {}
                if hasattr(response, 'accepted_buy_quote') and response.accepted_buy_quote:
                    try:
                        accepted_buy_quote = self.node._protobuf_to_dict(response.accepted_buy_quote)
                    except Exception as e:
                        logger.error(f"Error converting accepted_buy_quote: {e}")

                # Return result
                return {
                    "accepted_buy_quote": accepted_buy_quote,
                    "invoice_result": {
                        "r_hash": payment_hash,
                        "payment_request": payment_request
                    }
                }

            except Exception as e:
                logger.error(f"Error in invoice creation: {str(e)}")
                raise

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

            # Subscribe to invoice updates
            async for invoice in self.node.invoices_stub.SubscribeSingleInvoice(request):
                try:
                    # Map state to human-readable form
                    state_map = {0: "OPEN", 1: "SETTLED", 2: "CANCELED", 3: "ACCEPTED"}
                    state_name = state_map.get(invoice.state, f"UNKNOWN({invoice.state})")
                    logger.info(f"Invoice update: {payment_hash}, State: {state_name}")

                    # Check if the invoice is in the ACCEPTED state
                    if invoice.state == 3:  # ACCEPTED state
                        logger.info(f"Invoice {payment_hash} is ACCEPTED (state=3)")
                        
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
                                        logger.info(f"Raw record 65543 data: {value.hex()}")
                                        
                                        try:
                                            # Extract asset ID
                                            asset_id_marker = bytes.fromhex("0020")
                                            asset_id_pos = value.find(asset_id_marker)
                                            
                                            if asset_id_pos >= 0:
                                                asset_id_start = asset_id_pos + 2
                                                asset_id_end = asset_id_start + 32
                                                asset_id_bytes = value[asset_id_start:asset_id_end]
                                                asset_id = asset_id_bytes.hex()
                                                logger.info(f"Found asset ID marker at position {asset_id_pos}, extracted ID: {asset_id}")
                                                
                                                # Extract script key - EXACTLY 33 bytes after the 0x0140 marker
                                                script_key_marker = bytes.fromhex("0140")
                                                script_key_pos = value.find(script_key_marker, asset_id_end)
                                                
                                                if script_key_pos >= 0:
                                                    logger.info(f"Found script key marker at position {script_key_pos}")
                                                    script_key_start = script_key_pos + 2
                                                    script_key_end = script_key_start + 33  # Exactly 33 bytes
                                                    script_key = value[script_key_start:script_key_end]
                                                    script_key_hex = script_key.hex()
                                                    
                                                    logger.info(f"Extracted script key: {script_key_hex} (length: {len(script_key)} bytes)")
                                                    
                                                    # Store mapping
                                                    self._store_script_key_mapping(script_key_hex, payment_hash)
                                                    logger.info(f"Stored script key mapping: {script_key_hex} -> {payment_hash}")
                                                    script_key_found = True
                                                else:
                                                    logger.warning(f"Script key marker 0140 not found after asset ID")
                                            else:
                                                logger.warning(f"Asset ID marker not found in record")
                                        except Exception as e:
                                            logger.error(f"Error extracting script key from record: {e}", exc_info=True)

                                    # Process record 65536 (asset ID and amount)
                                    if 65536 in records and isinstance(records[65536], bytes):
                                        value = records[65536]
                                        logger.info(f"Processing asset info record (65536), length: {len(value)} bytes")
                                        logger.info(f"Raw record 65536 data: {value.hex()}")
                                        
                                        try:
                                            # Extract asset ID
                                            asset_id_marker = bytes.fromhex("0020")
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
                            self._store_script_key_mapping(payment_hash, payment_hash)
                            logger.info(f"No script key found, stored self-mapping for payment hash: {payment_hash}")
                        
                        # Debug values
                        logger.info(f"Extracted values - script_key_found: {script_key_found}, asset_id: {asset_id}, asset_amount: {asset_amount}")
                        
                        # Initiate asset transfer if we have all required info
                        if script_key_found and asset_id and asset_amount:
                            try:
                                logger.info(f"Initiating asset transfer - ID: {asset_id}, Script Key: {script_key_hex}, Amount: {asset_amount}")
                                transfer_result = await self.node.asset_manager.send_asset(
                                    asset_id=asset_id,
                                    script_key=script_key_hex,
                                    amount=asset_amount
                                )
                                logger.info(f"Asset transfer initiated successfully")
                                
                                # Try direct settlement from invoice manager
                                try:
                                    logger.info("🔄 INVOICE MANAGER: Attempting direct settlement after transfer...")
                                    preimage = self.node._get_preimage(payment_hash)
                                    if preimage:
                                        logger.info(f"🔑 INVOICE MANAGER: Found preimage for {payment_hash}")
                                        from .taproot_transfers import direct_settle_invoice
                                        settlement_result = await direct_settle_invoice(self.node, payment_hash)
                                        logger.info(f"⚡ INVOICE MANAGER: Direct settlement result: {settlement_result}")
                                    else:
                                        logger.warning(f"❌ INVOICE MANAGER: No preimage found for {payment_hash}")
                                except Exception as e:
                                    logger.error(f"❌ INVOICE MANAGER: Direct settlement failed: {e}", exc_info=True)
                            except Exception as e:
                                logger.error(f"Failed to initiate asset transfer: {e}", exc_info=True)
                        else:
                            logger.warning(f"Cannot initiate asset transfer: missing required information")
                        
                        logger.info("Waiting for asset transfer completion via monitor_asset_transfers (fallback path)")
                        break  # Exit loop after acceptance
                        
                    elif invoice.state == 1:  # SETTLED state
                        logger.info(f"Invoice {payment_hash} is already SETTLED")
                        break
                    elif invoice.state == 2:  # CANCELED state
                        logger.warning(f"Invoice {payment_hash} was CANCELED")
                        break
                
                except Exception as e:
                    logger.error(f"Error processing invoice update: {e}", exc_info=True)
                    continue

        except Exception as e:
            logger.error(f"Error monitoring invoice {payment_hash}: {e}", exc_info=True)
