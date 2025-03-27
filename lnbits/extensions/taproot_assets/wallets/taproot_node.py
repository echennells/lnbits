# /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/wallets/taproot_node.py
import os
import time
from typing import Optional, Dict, Any, List
import grpc
import grpc.aio
import json
import base64
from loguru import logger
from lnbits import bolt11

# Import the adapter module for Taproot Asset gRPC interfaces
from .taproot_adapter import (
    taprootassets_pb2,
    rfq_pb2,
    rfq_pb2_grpc,
    tapchannel_pb2,
    lightning_pb2,
    create_taprootassets_client,
    create_tapchannel_client,
    create_lightning_client
)

class TaprootAssetsNodeExtension:
    """
    Implementation of Taproot Assets node functionality for the extension.
    This mirrors the core TaprootAssetsNode class.
    """

    def __init__(
        self,
        wallet=None,
        host: str = None,
        network: str = None,
        tls_cert_path: str = None,
        macaroon_path: str = None,
        ln_macaroon_path: str = None,
        ln_macaroon_hex: str = None,
        tapd_macaroon_hex: str = None,
    ):
        from ..tapd_settings import taproot_settings

        self.wallet = wallet
        self.host = host or taproot_settings.tapd_host
        self.network = network or taproot_settings.tapd_network

        # Get paths from settings if not provided
        tls_cert_path = tls_cert_path or taproot_settings.tapd_tls_cert_path
        macaroon_path = macaroon_path or taproot_settings.tapd_macaroon_path
        ln_macaroon_path = ln_macaroon_path or taproot_settings.lnd_macaroon_path
        tapd_macaroon_hex = tapd_macaroon_hex or taproot_settings.tapd_macaroon_hex
        ln_macaroon_hex = ln_macaroon_hex or taproot_settings.lnd_macaroon_hex

        # Read TLS certificate
        try:
            with open(tls_cert_path, 'rb') as f:
                self.cert = f.read()
        except Exception as e:
            raise Exception(f"Failed to read TLS cert from {tls_cert_path}: {str(e)}")

        # Read Taproot macaroon
        if tapd_macaroon_hex:
            # Use the hex-encoded macaroon from settings
            self.macaroon = tapd_macaroon_hex
        else:
            try:
                with open(macaroon_path, 'rb') as f:
                    self.macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")

        # Read Lightning macaroon (for invoice creation)
        if ln_macaroon_hex:
            # Use the hex-encoded macaroon from settings
            self.ln_macaroon = ln_macaroon_hex
        else:
            try:
                with open(ln_macaroon_path, 'rb') as f:
                    self.ln_macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Lightning macaroon from {ln_macaroon_path}: {str(e)}")

        # Setup gRPC auth credentials for Taproot
        self.credentials = grpc.ssl_channel_credentials(self.cert)
        self.auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.macaroon)], None)
        )
        self.combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.auth_creds
        )

        # Setup gRPC auth credentials for Lightning
        self.ln_auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.ln_macaroon)], None)
        )
        self.ln_combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.ln_auth_creds
        )

        # Create async gRPC channels
        self.channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        self.stub = create_taprootassets_client(self.channel)

        # Create Lightning gRPC channel for invoice creation
        self.ln_channel = grpc.aio.secure_channel(self.host, self.ln_combined_creds)
        self.ln_stub = create_lightning_client(self.ln_channel)

        # Create TaprootAssetChannels gRPC channel for asset invoice creation
        self.tap_channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        self.tapchannel_stub = create_tapchannel_client(self.tap_channel)

    async def list_assets(self) -> List[Dict[str, Any]]:
        """List all Taproot Assets."""
        try:
            # Get all assets from tapd
            request = taprootassets_pb2.ListAssetRequest(
                with_witness=False,
                include_spent=False,
                include_leased=True,
                include_unconfirmed_mints=True
            )
            response = await self.stub.ListAssets(request, timeout=10)

            # Get all assets from the response
            assets = [
                {
                    "name": asset.asset_genesis.name.decode('utf-8') if isinstance(asset.asset_genesis.name, bytes) else asset.asset_genesis.name,
                    "asset_id": asset.asset_genesis.asset_id.hex() if isinstance(asset.asset_genesis.asset_id, bytes) else asset.asset_genesis.asset_id,
                    "type": str(asset.asset_genesis.asset_type),
                    "amount": str(asset.amount),
                    "genesis_point": asset.asset_genesis.genesis_point,
                    "meta_hash": asset.asset_genesis.meta_hash.hex() if isinstance(asset.asset_genesis.meta_hash, bytes) else asset.asset_genesis.meta_hash,
                    "version": str(asset.version),
                    "is_spent": asset.is_spent,
                    "script_key": asset.script_key.hex() if isinstance(asset.script_key, bytes) else asset.script_key
                }
                for asset in response.assets
            ]

            # Get channel assets information
            channel_assets = await self.list_channel_assets()

            # Create a mapping of asset_id to asset info for easier lookup
            asset_map = {asset["asset_id"]: asset for asset in assets}

            # Merge channel asset information with regular assets
            for channel_asset in channel_assets:
                asset_id = channel_asset["asset_id"]
                if asset_id in asset_map:
                    # Add channel information to existing asset
                    asset_map[asset_id]["channel_info"] = {
                        "channel_point": channel_asset["channel_point"],
                        "capacity": channel_asset["capacity"],
                        "local_balance": channel_asset["local_balance"],
                        "remote_balance": channel_asset["remote_balance"]
                    }
                else:
                    # This is a channel-only asset, add it to the map
                    # FIXED: Use the name from channel_asset instead of hardcoding "Unknown (Channel Asset)"
                    asset_map[asset_id] = {
                        "asset_id": asset_id,
                        "name": channel_asset["name"] or "Unknown (Channel Asset)",
                        "type": "CHANNEL_ONLY",
                        "amount": str(channel_asset["capacity"]),
                        "channel_info": {
                            "channel_point": channel_asset["channel_point"],
                            "capacity": channel_asset["capacity"],
                            "local_balance": channel_asset["local_balance"],
                            "remote_balance": channel_asset["remote_balance"]
                        }
                    }

            return list(asset_map.values())
        except Exception as e:
            logger.error(f"Failed to list assets: {str(e)}")
            return []  # Return empty list on any error

    async def list_channel_assets(self) -> List[Dict[str, Any]]:
        """
        List all Lightning channels with Taproot Assets.

        This method retrieves all Lightning channels and extracts Taproot asset information
        from channels with commitment type 4 or 6 (Taproot overlay).

        Returns:
            A list of dictionaries containing channel and asset information.
        """
        try:
            # Call the LND ListChannels endpoint
            request = lightning_pb2.ListChannelsRequest()
            response = await self.ln_stub.ListChannels(request, timeout=10)

            channel_assets = []

            # Process each channel
            for channel in response.channels:
                try:
                    # Check if the channel has custom_channel_data
                    if hasattr(channel, 'custom_channel_data') and channel.custom_channel_data:
                        try:
                            # Decode the custom_channel_data as UTF-8 JSON
                            asset_data = json.loads(channel.custom_channel_data.decode('utf-8'))

                            # Process each asset in the channel
                            for asset in asset_data.get("assets", []):
                                # Extract asset information from the nested structure
                                asset_utxo = asset.get("asset_utxo", {})

                                # Get asset_id from the correct location
                                asset_id = ""
                                if "asset_id" in asset_utxo:
                                    asset_id = asset_utxo["asset_id"]
                                elif "asset_genesis" in asset_utxo and "asset_id" in asset_utxo["asset_genesis"]:
                                    asset_id = asset_utxo["asset_genesis"]["asset_id"]

                                # Get name from the correct location
                                name = ""
                                if "name" in asset_utxo:
                                    name = asset_utxo["name"]
                                elif "asset_genesis" in asset_utxo and "name" in asset_utxo["asset_genesis"]:
                                    name = asset_utxo["asset_genesis"]["name"]

                                asset_info = {
                                    "asset_id": asset_id,
                                    "name": name,
                                    "channel_id": str(channel.chan_id),
                                    "channel_point": channel.channel_point,
                                    "remote_pubkey": channel.remote_pubkey,
                                    "capacity": asset.get("capacity", 0),
                                    "local_balance": asset.get("local_balance", 0),
                                    "remote_balance": asset.get("remote_balance", 0),
                                    "commitment_type": str(channel.commitment_type)
                                }

                                # Add to channel assets if it has an asset_id
                                if asset_info["asset_id"]:
                                    channel_assets.append(asset_info)
                        except Exception as e:
                            logger.debug(f"Failed to decode custom_channel_data for Chan ID {channel.chan_id}: {e}")
                except Exception as e:
                    logger.debug(f"Error processing channel {channel.channel_point}: {e}")
                    continue
            return channel_assets
        except Exception as e:
            logger.debug(f"Error in list_channel_assets: {e}")
            return []  # Return empty list instead of raising

    async def create_asset_invoice(self, memo: str, asset_id: str, asset_amount: int, expiry: Optional[int] = None) -> Dict[str, Any]:
        """
        Create an invoice for a Taproot Asset transfer.

        This uses the TaprootAssetChannels service's AddInvoice method that is specifically
        designed for asset invoices. The RFQ (Request for Quote) process is handled internally
        by the Taproot Assets daemon.

        Args:
            memo: Description for the invoice
            asset_id: The ID of the Taproot Asset
            asset_amount: The amount of the asset to transfer
            expiry: Optional expiry time in seconds

        Returns:
            Dict containing the invoice information with accepted_buy_quote and invoice_result
        """
        try:
            # DEBUG: Log the start of invoice creation with parameters
            logger.info(f"DEBUG: Starting asset invoice creation for asset_id={asset_id}, amount={asset_amount}")
            
            # Get channel assets to check if we have multiple channels for this asset
            channel_assets = await self.list_channel_assets()
            asset_channels = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
            channel_count = len(asset_channels)
            
            logger.info(f"DEBUG: Found {channel_count} channels for asset_id={asset_id}")
            for idx, channel in enumerate(asset_channels):
                logger.info(f"DEBUG: Channel {idx+1}: channel_point={channel.get('channel_point')}, local_balance={channel.get('local_balance')}")
            
            # Create RFQ client
            rfq_stub = rfq_pb2_grpc.RfqStub(self.channel)

            # Query peer accepted quotes
            try:
                logger.info("DEBUG: Querying peer accepted quotes")
                rfq_request = rfq_pb2.QueryPeerAcceptedQuotesRequest()
                
                # Log the full RFQ request
                logger.info(f"DEBUG: RFQ Request: {rfq_request}")
                
                rfq_response = await rfq_stub.QueryPeerAcceptedQuotes(rfq_request, timeout=10)
                
                # Log the full RFQ response
                logger.info(f"DEBUG: RFQ Response type: {type(rfq_response)}")
                logger.info(f"DEBUG: RFQ Response fields: {[f.name for f in rfq_response.DESCRIPTOR.fields]}")
                
                # Check if created_time exists in any response objects
                if hasattr(rfq_response, 'created_time'):
                    logger.info(f"DEBUG: RFQ Response has created_time field: {rfq_response.created_time}")
                else:
                    logger.info("DEBUG: RFQ Response does NOT have created_time field at top level")
                
                # Process buy quotes if needed
                logger.info(f"DEBUG: Found {len(rfq_response.buy_quotes)} buy quotes")
                for i, quote in enumerate(rfq_response.buy_quotes):
                    logger.info(f"DEBUG: Buy quote {i+1} fields: {[f.name for f in quote.DESCRIPTOR.fields]}")
                    
                    # Check if created_time exists in the quote
                    if hasattr(quote, 'created_time'):
                        logger.info(f"DEBUG: Buy quote {i+1} has created_time field: {quote.created_time}")
                    else:
                        logger.info(f"DEBUG: Buy quote {i+1} does NOT have created_time field")
                    
                    if hasattr(quote, 'asset_id'):
                        quote_asset_id = quote.asset_id.hex() if isinstance(quote.asset_id, bytes) else quote.asset_id
                        # Check if this quote is for the requested asset
                        if quote_asset_id == asset_id:
                            logger.info(f"DEBUG: Found buy quote for asset: {asset_id}")
                            
                            # Log all fields in the quote
                            for field_name in quote.DESCRIPTOR.fields_by_name:
                                value = getattr(quote, field_name)
                                logger.info(f"DEBUG: Quote field {field_name} = {value}")
            except Exception as e:
                logger.error(f"DEBUG: Error querying RFQ service: {e}", exc_info=True)

            # Convert asset_id from hex to bytes if needed
            asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id

            # Create a standard invoice for the invoice_request field
            invoice = lightning_pb2.Invoice(
                memo=memo if memo else "Taproot Asset Transfer",
                value=0,  # The value will be determined by the RFQ process
                private=True
            )
            
            # Log the invoice object
            logger.info(f"DEBUG: Invoice object fields: {[f.name for f in invoice.DESCRIPTOR.fields]}")
            if hasattr(invoice, 'created_time'):
                logger.info(f"DEBUG: Invoice has created_time field: {invoice.created_time}")
            else:
                logger.info("DEBUG: Invoice does NOT have created_time field")

            # Create the AddInvoiceRequest using the tapchannel_pb2 definition
            try:
                # Check if we need to add created_time for multi-channel scenarios
                if channel_count > 1:
                    logger.info("DEBUG: Multi-channel scenario detected, checking if we need to add created_time")
                    # Check if the Invoice object has a created_time field
                    if hasattr(invoice, 'created_time'):
                        # Set created_time to current Unix timestamp
                        current_time = int(time.time())
                        logger.info(f"DEBUG: Setting created_time to {current_time}")
                        invoice.created_time = current_time
                
                request = tapchannel_pb2.AddInvoiceRequest(
                    asset_id=asset_id_bytes,
                    asset_amount=asset_amount,
                    invoice_request=invoice
                )
                
                # Log the full request
                logger.info(f"DEBUG: AddInvoiceRequest fields: {[f.name for f in request.DESCRIPTOR.fields]}")
                logger.info(f"DEBUG: AddInvoiceRequest asset_id: {request.asset_id.hex() if isinstance(request.asset_id, bytes) else request.asset_id}")
                logger.info(f"DEBUG: AddInvoiceRequest asset_amount: {request.asset_amount}")
                
                # Check if the request has created_time
                if hasattr(request, 'created_time'):
                    logger.info(f"DEBUG: AddInvoiceRequest has created_time field: {request.created_time}")
                else:
                    logger.info("DEBUG: AddInvoiceRequest does NOT have created_time field")

                # Call the TaprootAssetChannels AddInvoice method
                logger.info("DEBUG: Calling TaprootAssetChannels.AddInvoice")
                response = await self.tapchannel_stub.AddInvoice(request, timeout=30)
                logger.info("DEBUG: Successfully received response from AddInvoice")
            except Exception as e:
                logger.error(f"DEBUG: Error creating or sending AddInvoiceRequest: {e}", exc_info=True)
                raise

            # Log the full response for debugging
            logger.info(f"DEBUG: Raw response from AddInvoice: {response}")
            logger.info(f"DEBUG: Response type: {type(response)}")
            logger.info(f"DEBUG: Response fields: {[f.name for f in response.DESCRIPTOR.fields]}")
            
            # Check if the response has created_time
            if hasattr(response, 'created_time'):
                logger.info(f"DEBUG: Response has created_time field: {response.created_time}")
            else:
                logger.info("DEBUG: Response does NOT have created_time field at top level")
            
            # Check if invoice_result has created_time
            if hasattr(response.invoice_result, 'created_time'):
                logger.info(f"DEBUG: invoice_result has created_time field: {response.invoice_result.created_time}")
            else:
                logger.info("DEBUG: invoice_result does NOT have created_time field")

            # Extract the payment hash and payment request from the invoice_result
            payment_hash = response.invoice_result.r_hash
            if isinstance(payment_hash, bytes):
                payment_hash = payment_hash.hex()
            logger.info(f"DEBUG: Extracted payment_hash: {payment_hash}")

            payment_request = response.invoice_result.payment_request
            logger.info(f"DEBUG: Extracted payment_request: {payment_request[:30]}...")

            # Helper function to convert protobuf message to a JSON-serializable dict
            def protobuf_to_dict(pb_obj):
                """Convert a protobuf object to a JSON-serializable dict."""
                if pb_obj is None:
                    return None

                result = {}

                # Get all fields from the protobuf object
                for field_name in pb_obj.DESCRIPTOR.fields_by_name:
                    value = getattr(pb_obj, field_name)
                    
                    # Log each field for debugging
                    logger.info(f"DEBUG: Processing field {field_name} with value type {type(value)}")

                    # Handle different types of values
                    if isinstance(value, bytes):
                        # Convert bytes to hex string
                        result[field_name] = value.hex()
                    elif hasattr(value, 'DESCRIPTOR'):
                        # Recursively convert nested protobuf objects
                        logger.info(f"DEBUG: Converting nested protobuf object for field {field_name}")
                        result[field_name] = protobuf_to_dict(value)
                    elif isinstance(value, (list, tuple)):
                        # Handle repeated fields - ensure we convert tuples to dictionaries
                        logger.info(f"DEBUG: Converting list/tuple for field {field_name} with {len(value)} items")
                        result[field_name] = [
                            protobuf_to_dict(item) if hasattr(item, 'DESCRIPTOR') else item
                            for item in value
                        ]
                    else:
                        # Primitive types (int, float, bool, str)
                        result[field_name] = value

                return result

            # Convert the accepted_buy_quote to a dictionary
            accepted_buy_quote = {}

            if hasattr(response, 'accepted_buy_quote') and response.accepted_buy_quote:
                try:
                    logger.info(f"DEBUG: Processing accepted_buy_quote of type {type(response.accepted_buy_quote)}")
                    
                    # Check if accepted_buy_quote has created_time
                    if hasattr(response.accepted_buy_quote, 'created_time'):
                        logger.info(f"DEBUG: accepted_buy_quote has created_time field: {response.accepted_buy_quote.created_time}")
                    else:
                        logger.info("DEBUG: accepted_buy_quote does NOT have created_time field")
                    
                    # Log all fields in accepted_buy_quote
                    logger.info(f"DEBUG: accepted_buy_quote fields: {[f.name for f in response.accepted_buy_quote.DESCRIPTOR.fields]}")
                    
                    # Convert the protobuf message to a dictionary using our helper function
                    accepted_buy_quote = protobuf_to_dict(response.accepted_buy_quote)
                    logger.info(f"DEBUG: Converted accepted_buy_quote to dict with keys: {list(accepted_buy_quote.keys())}")

                    # Ensure accepted_buy_quote is a dictionary, not a tuple or other type
                    if not isinstance(accepted_buy_quote, dict):
                        logger.warning(f"DEBUG: accepted_buy_quote is not a dict after conversion: {type(accepted_buy_quote)}")
                        # Convert to dictionary if it's a tuple or other non-dict type
                        if isinstance(accepted_buy_quote, (list, tuple)):
                            accepted_buy_quote = {"items": list(accepted_buy_quote)}
                        else:
                            accepted_buy_quote = {"value": str(accepted_buy_quote)}
                except Exception as e:
                    logger.error(f"DEBUG: Error converting accepted_buy_quote to dictionary: {e}", exc_info=True)
                    # Provide a fallback empty dict if conversion fails
                    accepted_buy_quote = {}

            # Return the invoice information in the format expected by the client
            result = {
                "accepted_buy_quote": accepted_buy_quote,
                "invoice_result": {
                    "r_hash": payment_hash,
                    "payment_request": payment_request
                }
            }

            # Check if created_time exists in the final result
            if "created_time" in accepted_buy_quote:
                logger.info(f"DEBUG: Final result has created_time in accepted_buy_quote: {accepted_buy_quote['created_time']}")
            else:
                logger.info("DEBUG: Final result does NOT have created_time in accepted_buy_quote")

            logger.info(f"DEBUG: Final result from create_asset_invoice: {result}")
            logger.info(f"DEBUG: accepted_buy_quote type in result: {type(result['accepted_buy_quote'])}")

            return result
        except Exception as e:
            logger.error(f"DEBUG: Failed to create asset invoice: {str(e)}", exc_info=True)
            # Log the full exception traceback
            import traceback
            logger.error(f"DEBUG: Full exception traceback: {traceback.format_exc()}")
            raise Exception(f"Failed to create asset invoice: {str(e)}")

    async def pay_asset_invoice(
        self,
        payment_request: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pay a Taproot Asset invoice.

        Args:
            payment_request: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            asset_id: Optional asset ID to use for payment. If not provided, 
                      will attempt to extract from invoice metadata.

        Returns:
            Dict with payment details
        """
        try:
            logger.debug(f"Paying asset invoice: {payment_request[:30]}...")

            # If fee_limit_sats is not provided, use a default
            if fee_limit_sats is None:
                fee_limit_sats = 1000  # Default to 1000 sats fee limit
            
            # Get payment hash and try to extract asset ID from the invoice
            payment_hash = ""
            try:
                from lnbits import bolt11
                decoded = bolt11.decode(payment_request)
                payment_hash = decoded.payment_hash
                logger.debug(f"Decoded invoice: payment_hash={payment_hash}, amount_msat={decoded.amount_msat}")
                
                # Try to extract asset ID from invoice metadata if not provided
                if not asset_id and decoded.tags:
                    for tag in decoded.tags:
                        # Look for asset ID in description or other tags
                        if tag[0] == 'd' and 'asset_id=' in tag[1]:
                            # Extract asset ID from description
                            import re
                            asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', tag[1])
                            if asset_id_match:
                                asset_id = asset_id_match.group(1)
                                logger.debug(f"Extracted asset_id from invoice: {asset_id}")
                                break
            except Exception as e:
                logger.warning(f"Failed to decode invoice: {e}")
            
            # If asset_id is still not available, try to get it from available assets
            if not asset_id:
                try:
                    logger.debug("Asset ID not found in invoice, checking available assets")
                    assets = await self.list_assets()
                    if assets and len(assets) > 0:
                        # Use the first available asset as fallback
                        asset_id = assets[0]["asset_id"]
                        logger.debug(f"Using first available asset: {asset_id}")
                    else:
                        raise Exception("No asset ID provided and no assets available")
                except Exception as e:
                    logger.error(f"Failed to get assets: {e}")
                    raise Exception("No asset ID provided and failed to get available assets")
            
            logger.debug(f"Using asset_id: {asset_id}")
            
            # Convert asset_id to bytes
            asset_id_bytes = bytes.fromhex(asset_id)
            
            # Try to pay the invoice with Lightning directly first
            try:
                # Import the router pb2 module
                from lnbits.wallets.lnd_grpc_files.routerrpc import router_pb2
                
                # Create the router payment request
                router_payment_request = router_pb2.SendPaymentRequest(
                    payment_request=payment_request,
                    fee_limit_sat=fee_limit_sats,
                    timeout_seconds=60,  # 1 minute timeout
                    no_inflight_updates=False
                )
                
                # Create the SendPayment request
                request = tapchannel_pb2.SendPaymentRequest(
                    payment_request=router_payment_request,
                    asset_id=asset_id_bytes,  # Include the asset ID
                    allow_overpay=True  # Allow payment even if it's uneconomical
                )
                
                logger.debug(f"Calling tapchannel_stub.SendPayment with asset_id={asset_id}")
                
                # Important: Do not await the initial call to SendPayment
                # Just get the stream object
                response_stream = self.tapchannel_stub.SendPayment(request)
                
                # Prepare variables to hold payment result information
                payment_status = "pending"
                preimage = ""
                fee_sat = 0
                
                # Process the stream responses
                try:
                    # Now we use async for to iterate through the stream responses
                    async for response in response_stream:
                        logger.debug(f"Got payment response: {response}")
                        
                        # Check if we got a sell order acceptance or payment result
                        if hasattr(response, 'accepted_sell_order') and response.HasField('accepted_sell_order'):
                            logger.debug("Received accepted sell order response")
                            # This is just an intermediate step, continue to next response
                            continue
                            
                        elif hasattr(response, 'payment_result') and response.HasField('payment_result'):
                            payment_result = response.payment_result
                            
                            # Check payment status
                            if payment_result.status == 1:  # SUCCEEDED
                                payment_status = "success"
                                
                                if hasattr(payment_result, 'payment_preimage'):
                                    preimage = payment_result.payment_preimage.hex() if isinstance(payment_result.payment_preimage, bytes) else str(payment_result.payment_preimage)
                                
                                if hasattr(payment_result, 'fee_msat'):
                                    fee_sat = payment_result.fee_msat // 1000
                                
                                logger.debug(f"Payment succeeded: hash={payment_hash}, preimage={preimage}, fee={fee_sat} sat")
                                break
                                
                            elif payment_result.status == 3:  # FAILED
                                payment_status = "failed"
                                failure_reason = "Unknown failure"
                                
                                if hasattr(payment_result, 'failure_reason'):
                                    failure_reason = payment_result.failure_reason
                                    
                                logger.error(f"Payment failed: {failure_reason}")
                                raise Exception(f"Payment failed: {failure_reason}")
                    
                    # Check final payment status
                    if payment_status != "success":
                        raise Exception("Payment did not succeed or timed out")
                        
                except grpc.aio.AioRpcError as e:
                    # Handle gRPC errors from the streaming call
                    logger.error(f"gRPC error in payment stream: {e.code()}: {e.details()}")
                    raise Exception(f"gRPC error: {e.code()}: {e.details()}")
                    
                except Exception as e:
                    # Handle other errors
                    logger.error(f"Error processing payment stream: {e}")
                    raise
                
                # Prepare successful response
                result = {
                    "payment_hash": payment_hash,
                    "payment_preimage": preimage,
                    "fee_sats": fee_sat,
                    "status": "success",
                    "payment_request": payment_request
                }
                
                logger.debug(f"Payment successful: {result}")
                return result
                
            except Exception as e:
                logger.error(f"Failed to pay using Taproot channel: {e}")
                
                # If the Taproot-specific payment failed, fall back to standard Lightning payment
                try:
                    logger.debug("Falling back to standard Lightning payment")
                    
                    # Create payment request with fee limit
                    fee_limit_obj = lightning_pb2.FeeLimit(fixed=fee_limit_sats * 1000)  # Convert to millisatoshis
                    
                    request = lightning_pb2.SendRequest(
                        payment_request=payment_request,
                        fee_limit=fee_limit_obj,
                        allow_self_payment=True
                    )
                    
                    # Make the SendPaymentSync call
                    response = await self.ln_stub.SendPaymentSync(request)
                    
                    # Check for errors
                    if hasattr(response, 'payment_error') and response.payment_error:
                        logger.error(f"Payment failed: {response.payment_error}")
                        raise Exception(f"Payment failed: {response.payment_error}")
                    
                    # Extract payment details
                    preimage = ""
                    fee_sat = 0
                    
                    if hasattr(response, 'payment_preimage'):
                        preimage = response.payment_preimage.hex() if isinstance(response.payment_preimage, bytes) else str(response.payment_preimage)
                    
                    if hasattr(response, 'payment_route') and hasattr(response.payment_route, 'total_fees_msat'):
                        fee_sat = response.payment_route.total_fees_msat // 1000
                    
                    # Prepare successful response
                    result = {
                        "payment_hash": payment_hash,
                        "payment_preimage": preimage,
                        "fee_sats": fee_sat,
                        "status": "success",
                        "payment_request": payment_request
                    }
                    
                    logger.debug(f"Standard Lightning payment successful: {result}")
                    return result
                    
                except Exception as fallback_error:
                    logger.error(f"Fallback Lightning payment also failed: {fallback_error}")
                    raise Exception(f"All payment methods failed. Last error: {str(fallback_error)}")
                
        except Exception as e:
            logger.error(f"Payment failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to pay asset invoice: {str(e)}")

    async def update_after_payment(
        self,
        payment_request: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update Taproot Assets after a payment has been made through the LNbits wallet.

        This method notifies the Taproot Asset daemon that a payment has been completed
        so it can update its internal state, but doesn't actually send any Bitcoin payment
        since that was already handled by the LNbits wallet system.

        Args:
            payment_request: The original BOLT11 invoice
            payment_hash: The payment hash of the completed payment
            fee_limit_sats: Optional fee limit in satoshis (not used for actual payment now)
            asset_id: Optional asset ID to use for the update. If not provided, 
                      will attempt to extract from invoice metadata.

        Returns:
            Dict containing the update confirmation
        """
        try:
            # Try to extract asset_id from the payment_request if not provided
            if not asset_id:
                try:
                    from lnbits import bolt11
                    decoded = bolt11.decode(payment_request)
                    
                    # Try to extract asset ID from invoice metadata
                    if decoded.tags:
                        for tag in decoded.tags:
                            # Look for asset ID in description or other tags
                            if tag[0] == 'd' and 'asset_id=' in tag[1]:
                                # Extract asset ID from description
                                import re
                                asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', tag[1])
                                if asset_id_match:
                                    asset_id = asset_id_match.group(1)
                                    logger.debug(f"Extracted asset_id from invoice: {asset_id}")
                                    break
                except Exception as e:
                    logger.warning(f"Failed to extract asset ID from invoice: {e}")
            
            # If asset_id is still not available, try to get it from available assets
            if not asset_id:
                try:
                    logger.debug("Asset ID not found in invoice, checking available assets")
                    assets = await self.list_assets()
                    if assets and len(assets) > 0:
                        # Use the first available asset as fallback
                        asset_id = assets[0]["asset_id"]
                        logger.debug(f"Using first available asset: {asset_id}")
                    else:
                        raise Exception("No asset ID provided and no assets available")
                except Exception as e:
                    logger.error(f"Failed to get assets: {e}")
                    raise Exception("No asset ID provided and failed to get available assets")
            
            logger.debug(f"Updating Taproot Assets after payment, asset_id={asset_id}, payment_hash={payment_hash}")

            # Convert asset_id to bytes
            asset_id_bytes = bytes.fromhex(asset_id)

            # Create a notification request to the Taproot daemon
            from lnbits.wallets.lnd_grpc_files.routerrpc import router_pb2

            # Import the tapchannel pb2 module
            from .taproot_adapter import tapchannel_pb2

            # Create a notification request
            request = tapchannel_pb2.PaymentNotificationRequest(
                payment_hash=bytes.fromhex(payment_hash),
                asset_id=asset_id_bytes,
                status="SUCCEEDED"
            )

            logger.debug(f"Sending payment notification to Taproot daemon")

            # Send the notification to the Taproot daemon
            response = await self.tapchannel_stub.NotifyPaymentStatus(request, timeout=30)

            result = {
                "success": True,
                "payment_hash": payment_hash,
                "message": "Taproot Assets updated successfully",
                "preimage": payment_hash  # Typically we'd get this from the actual payment
            }

            logger.debug(f"Taproot Assets update result: {result}")
            return result

        except Exception as e:
            logger.error(f"Failed to update Taproot Assets after payment: {str(e)}", exc_info=True)
            raise Exception(f"Failed to update Taproot Assets: {str(e)}")

    async def close(self):
        """Close the gRPC channels."""
        await self.channel.close()
        await self.ln_channel.close()
        await self.tap_channel.close()
