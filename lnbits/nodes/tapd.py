import os
import time
from typing import Optional, Dict, Any
import grpc
import grpc.aio
import json
import base64
from lnbits import bolt11

# Import the adapter module for Taproot Asset gRPC interfaces
from lnbits.wallets.taproot_adapter import (
    taprootassets_pb2,
    rfq_pb2,
    rfq_pb2_grpc,
    tapchannel_pb2,
    lightning_pb2,
    router_pb2,
    create_taprootassets_client,
    create_tapchannel_client,
    create_lightning_client
)

class TaprootAssetsNode:
    """
    Implementation of Taproot Assets node functionality.
    This is separate from the base Node class since Taproot Assets 
    have different capabilities than Lightning nodes.
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

    async def list_assets(self) -> list[dict]:
        """List all Taproot Assets."""
        try:
            # Get all assets from tapd
            request = taprootassets_pb2.ListAssetRequest(  # type: ignore
                with_witness=False,
                include_spent=False,  # Changed to avoid conflict with include_leased
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
            
    async def list_channel_assets(self) -> list[dict]:
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
                            print(f"DEBUG:tapd:Taproot Assets for Chan ID {channel.chan_id}: {asset_data}")
                            
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
                                    print(f"DEBUG:tapd:Added asset {asset_info['asset_id']} to channel {channel.channel_point}")
                        except Exception as e:
                            print(f"DEBUG:tapd:Failed to decode custom_channel_data for Chan ID {channel.chan_id}: {e}")
                    else:
                        print(f"DEBUG:tapd:Chan ID {channel.chan_id} has no Taproot assets")
                except Exception as e:
                    print(f"DEBUG:tapd:Error processing channel {channel.channel_point}: {e}")
                    continue
            
            print(f"DEBUG:tapd:Returning {len(channel_assets)} channel assets")
            return channel_assets
        except Exception as e:
            print(f"DEBUG:tapd:Error in list_channel_assets: {e}")
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
            # First, check if there are any buy offers for this asset
            print(f"DEBUG:tapd:Checking RFQ offers for asset: {asset_id}")
            
            # Create RFQ client
            rfq_stub = rfq_pb2_grpc.RfqStub(self.channel)
            
            # Query peer accepted quotes
            try:
                print(f"DEBUG:tapd:Creating QueryPeerAcceptedQuotesRequest")
                rfq_request = rfq_pb2.QueryPeerAcceptedQuotesRequest()
                print(f"DEBUG:tapd:QueryPeerAcceptedQuotesRequest created: {rfq_request}")
                print(f"DEBUG:tapd:rfq_stub type: {type(rfq_stub)}")
                print(f"DEBUG:tapd:rfq_stub methods: {dir(rfq_stub)}")
                
                print(f"DEBUG:tapd:Calling QueryPeerAcceptedQuotes")
                rfq_response = await rfq_stub.QueryPeerAcceptedQuotes(rfq_request, timeout=10)
                print(f"DEBUG:tapd:QueryPeerAcceptedQuotes response type: {type(rfq_response)}")
                print(f"DEBUG:tapd:QueryPeerAcceptedQuotes response attributes: {dir(rfq_response)}")
                print(f"DEBUG:tapd:Found {len(rfq_response.buy_quotes)} buy quotes and {len(rfq_response.sell_quotes)} sell quotes")
                
                # Log buy quotes
                for i, quote in enumerate(rfq_response.buy_quotes):
                    print(f"DEBUG:tapd:Buy Quote {i+1}:")
                    print(f"DEBUG:tapd:  Quote type: {type(quote)}")
                    print(f"DEBUG:tapd:  Quote attributes: {dir(quote)}")
                    print(f"DEBUG:tapd:  Peer: {quote.peer}")
                    print(f"DEBUG:tapd:  SCID: {quote.scid}")
                    print(f"DEBUG:tapd:  Asset Max Amount: {quote.asset_max_amount}")
                    
                    # Check if the quote has an asset_id field
                    if hasattr(quote, 'asset_id'):
                        quote_asset_id = quote.asset_id.hex() if isinstance(quote.asset_id, bytes) else quote.asset_id
                        print(f"DEBUG:tapd:  Asset ID: {quote_asset_id}")
                        # Check if this quote is for the requested asset
                        if quote_asset_id == asset_id:
                            print(f"DEBUG:tapd:  This quote is for the requested asset: {asset_id}")
                    
                    if hasattr(quote, 'ask_asset_rate'):
                        print(f"DEBUG:tapd:  Ask Asset Rate: {quote.ask_asset_rate.coefficient} (scale: {quote.ask_asset_rate.scale})")
                
                # Note: QueryAssetQuotesRequest is not available in the current protobuf definitions
                # We'll rely on the AddInvoice method to find a buy quote for this asset
                print(f"DEBUG:tapd:QueryAssetQuotesRequest is not available in the current protobuf definitions")
                print(f"DEBUG:tapd:We'll rely on the AddInvoice method to find a buy quote for this asset")
            except Exception as e:
                print(f"DEBUG:tapd:Error querying RFQ service: {e}")
                print(f"DEBUG:tapd:Error type: {type(e)}")
            
            # Convert asset_id from hex to bytes if needed
            asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id
            
            # Create a standard invoice for the invoice_request field
            invoice = lightning_pb2.Invoice(
                memo=memo if memo else "Taproot Asset Transfer",
                value=0,  # The value will be determined by the RFQ process
                private=True
            )
            
            # Create the AddInvoiceRequest using the tapchannel_pb2 definition
            # This is the correct way to create an asset invoice
            try:
                print(f"DEBUG:tapd:Creating AddInvoiceRequest with asset_id={asset_id}, asset_amount={asset_amount}")
                print(f"DEBUG:tapd:asset_id_bytes type: {type(asset_id_bytes)}, length: {len(asset_id_bytes)}")
                print(f"DEBUG:tapd:invoice type: {type(invoice)}")
                print(f"DEBUG:tapd:invoice attributes: {dir(invoice)}")
                
                request = tapchannel_pb2.AddInvoiceRequest(
                    asset_id=asset_id_bytes,
                    asset_amount=asset_amount,
                    invoice_request=invoice
                )
                
                # Debug the request
                print(f"DEBUG:tapd:AddInvoiceRequest created successfully")
                print(f"DEBUG:tapd:AddInvoiceRequest type: {type(request)}")
                print(f"DEBUG:tapd:AddInvoiceRequest attributes: {dir(request)}")
                
                # Call the TaprootAssetChannels AddInvoice method
                print(f"DEBUG:tapd:Calling TaprootAssetChannels.AddInvoice with asset_id={asset_id}, asset_amount={asset_amount}")
                print(f"DEBUG:tapd:tapchannel_stub type: {type(self.tapchannel_stub)}")
                print(f"DEBUG:tapd:tapchannel_stub methods: {dir(self.tapchannel_stub)}")
                
                response = await self.tapchannel_stub.AddInvoice(request, timeout=30)
                print(f"DEBUG:tapd:AddInvoice call successful")
            except Exception as e:
                print(f"DEBUG:tapd:Error creating or sending AddInvoiceRequest: {e}")
                print(f"DEBUG:tapd:Error type: {type(e)}")
                raise
            
            # Debug response
            print(f"DEBUG:tapd:AddInvoice response type: {type(response)}")
            print(f"DEBUG:tapd:AddInvoice response attributes: {dir(response)}")
            
            # Extract the payment hash and payment request from the invoice_result
            # The AddInvoiceResponse has two fields: accepted_buy_quote and invoice_result
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
                        # Handle repeated fields
                        result[field_name] = [
                            protobuf_to_dict(item) if hasattr(item, 'DESCRIPTOR') else item
                            for item in value
                        ]
                    else:
                        # Primitive types (int, float, bool, str)
                        result[field_name] = value
                
                return result
            
            # Convert the accepted_buy_quote to a dictionary
            accepted_buy_quote = None
            print(f"DEBUG:tapd:Checking for accepted_buy_quote in response")
            print(f"DEBUG:tapd:Response has accepted_buy_quote attribute: {hasattr(response, 'accepted_buy_quote')}")
            
            if hasattr(response, 'accepted_buy_quote') and response.accepted_buy_quote:
                print(f"DEBUG:tapd:accepted_buy_quote value: {response.accepted_buy_quote}")
                print(f"DEBUG:tapd:accepted_buy_quote type: {type(response.accepted_buy_quote)}")
                
                try:
                    # Convert the protobuf message to a dictionary using our helper function
                    accepted_buy_quote = protobuf_to_dict(response.accepted_buy_quote)
                    print(f"DEBUG:tapd:Got accepted_buy_quote from response: {accepted_buy_quote}")
                except Exception as e:
                    print(f"DEBUG:tapd:Error converting accepted_buy_quote to dictionary: {e}")
                    print(f"DEBUG:tapd:Error type: {type(e)}")
                    # Provide a fallback empty dict if conversion fails
                    accepted_buy_quote = {}
            else:
                print(f"DEBUG:tapd:accepted_buy_quote is empty or None")
                accepted_buy_quote = {}
            
            # Return the invoice information in the format expected by the client
            return {
                "accepted_buy_quote": accepted_buy_quote,
                "invoice_result": {
                    "r_hash": payment_hash,
                    "payment_request": payment_request,
                    "add_index": add_index,
                    "payment_addr": payment_addr
                }
            }
        except Exception as e:
            raise Exception(f"Failed to create asset invoice: {str(e)}")

    async def close(self):
        """Close the gRPC channels."""
        await self.channel.close()
        await self.ln_channel.close()
        await self.tap_channel.close()
