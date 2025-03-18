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
        from lnbits.settings import settings

        self.wallet = wallet
        self.host = host or settings.tapd_host
        self.network = network or settings.tapd_network

        # Get paths from settings if not provided
        tls_cert_path = tls_cert_path or settings.tapd_tls_cert_path
        macaroon_path = macaroon_path or settings.tapd_macaroon_path
        ln_macaroon_path = ln_macaroon_path or settings.lnd_macaroon_path
        tapd_macaroon_hex = tapd_macaroon_hex or settings.tapd_macaroon_hex
        ln_macaroon_hex = ln_macaroon_hex or settings.lnd_macaroon_hex

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
                    asset_map[asset_id] = {
                        "asset_id": asset_id,
                        "name": "Unknown (Channel Asset)",
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
            raise Exception(f"Failed to list assets: {str(e)}")

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
            raise Exception(f"Failed to list channel assets: {str(e)}")

    async def create_asset_invoice(self, memo: str, asset_id: str, asset_amount: int) -> Dict[str, Any]:
        """
        Create an invoice for a Taproot Asset transfer.

        This uses the TaprootAssetChannels service's AddInvoice method that is specifically
        designed for asset invoices. The RFQ (Request for Quote) process is handled internally
        by the Taproot Assets daemon.

        Args:
            memo: Description for the invoice
            asset_id: The ID of the Taproot Asset
            asset_amount: The amount of the asset to transfer

        Returns:
            Dict containing the invoice information with accepted_buy_quote and invoice_result
        """
        try:
            # Create RFQ client
            rfq_stub = rfq_pb2_grpc.RfqStub(self.channel)

            # Query peer accepted quotes
            try:
                rfq_request = rfq_pb2.QueryPeerAcceptedQuotesRequest()
                rfq_response = await rfq_stub.QueryPeerAcceptedQuotes(rfq_request, timeout=10)

                # Process buy quotes if needed
                for quote in rfq_response.buy_quotes:
                    if hasattr(quote, 'asset_id'):
                        quote_asset_id = quote.asset_id.hex() if isinstance(quote.asset_id, bytes) else quote.asset_id
                        # Check if this quote is for the requested asset
                        if quote_asset_id == asset_id:
                            logger.debug(f"Found buy quote for asset: {asset_id}")
            except Exception as e:
                logger.debug(f"Error querying RFQ service: {e}")

            # Convert asset_id from hex to bytes if needed
            asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id

            # Create a standard invoice for the invoice_request field
            invoice = lightning_pb2.Invoice(
                memo=memo if memo else "Taproot Asset Transfer",
                value=0,  # The value will be determined by the RFQ process
                private=True
            )

            # Create the AddInvoiceRequest using the tapchannel_pb2 definition
            try:
                request = tapchannel_pb2.AddInvoiceRequest(
                    asset_id=asset_id_bytes,
                    asset_amount=asset_amount,
                    invoice_request=invoice
                )

                # Call the TaprootAssetChannels AddInvoice method
                response = await self.tapchannel_stub.AddInvoice(request, timeout=30)
            except Exception as e:
                logger.debug(f"Error creating or sending AddInvoiceRequest: {e}")
                raise

            # Just log the response for debugging
            logger.debug(f"Raw response from AddInvoice: {response}")
            logger.debug(f"Response type: {type(response)}")

            # Log if accepted_buy_quote exists
            if hasattr(response, 'accepted_buy_quote') and response.accepted_buy_quote:
                logger.debug(f"Raw accepted_buy_quote: {response.accepted_buy_quote}")
                logger.debug(f"Type of accepted_buy_quote: {type(response.accepted_buy_quote)}")

            # Extract the payment hash and payment request from the invoice_result
            payment_hash = response.invoice_result.r_hash
            if isinstance(payment_hash, bytes):
                payment_hash = payment_hash.hex()

            payment_request = response.invoice_result.payment_request

            # Get the payment address if available
            payment_addr = ""
            if hasattr(response.invoice_result, 'payment_addr'):
                payment_addr = response.invoice_result.payment_addr
                if isinstance(payment_addr, bytes):
                    payment_addr = payment_addr.hex()

            # Get the add_index if available
            add_index = ""
            if hasattr(response.invoice_result, 'add_index'):
                add_index = str(response.invoice_result.add_index)

            # Helper function to convert protobuf message to a JSON-serializable dict
            def protobuf_to_dict(pb_obj):
                """Convert a protobuf object to a JSON-serializable dict."""
                if pb_obj is None:
                    return None

                result = {}

                # Get all fields from the protobuf object
                for field_name in pb_obj.DESCRIPTOR.fields_by_name:
                    value = getattr(pb_obj, field_name)

                    # Handle different types of values
                    if isinstance(value, bytes):
                        # Convert bytes to hex string
                        result[field_name] = value.hex()
                    elif hasattr(value, 'DESCRIPTOR'):
                        # Recursively convert nested protobuf objects
                        result[field_name] = protobuf_to_dict(value)
                    elif isinstance(value, (list, tuple)):
                        # Handle repeated fields - ensure we convert tuples to dictionaries
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
                    # Convert the protobuf message to a dictionary using our helper function
                    accepted_buy_quote = protobuf_to_dict(response.accepted_buy_quote)
                    
                    # Ensure accepted_buy_quote is a dictionary, not a tuple or other type
                    if not isinstance(accepted_buy_quote, dict):
                        logger.warning(f"accepted_buy_quote is not a dict after conversion: {type(accepted_buy_quote)}")
                        # Convert to dictionary if it's a tuple or other non-dict type
                        if isinstance(accepted_buy_quote, (list, tuple)):
                            accepted_buy_quote = {"items": list(accepted_buy_quote)}
                        else:
                            accepted_buy_quote = {"value": str(accepted_buy_quote)}
                except Exception as e:
                    logger.error(f"Error converting accepted_buy_quote to dictionary: {e}", exc_info=True)
                    # Provide a fallback empty dict if conversion fails
                    accepted_buy_quote = {}

            # Return the invoice information in the format expected by the client
            result = {
                "accepted_buy_quote": accepted_buy_quote,
                "invoice_result": {
                    "r_hash": payment_hash,
                    "payment_request": payment_request,
                    "add_index": add_index,
                    "payment_addr": payment_addr
                }
            }
            
            logger.debug(f"Final result from create_asset_invoice: {result}")
            logger.debug(f"accepted_buy_quote type in result: {type(result['accepted_buy_quote'])}")
            
            return result
        except Exception as e:
            raise Exception(f"Failed to create asset invoice: {str(e)}")

    async def close(self):
        """Close the gRPC channels."""
        await self.channel.close()
        await self.ln_channel.close()
        await self.tap_channel.close()
