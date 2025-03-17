import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Any

from loguru import logger

from lnbits.settings import settings

from .taproot_adapter import (
    create_taprootassets_client,
    create_tapchannel_client,
    create_lightning_client,
)

from ..crud import get_or_create_settings


class InvoiceResponse:
    """Response from invoice creation."""
    
    def __init__(
        self,
        ok: bool,
        payment_hash: Optional[str] = None,
        payment_request: Optional[str] = None,
        error_message: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.ok = ok
        self.payment_hash = payment_hash
        self.payment_request = payment_request
        self.error_message = error_message
        self.extra = extra or {}
        self.checking_id = payment_hash


class PaymentResponse:
    """Response from payment."""
    
    def __init__(
        self,
        ok: Optional[bool] = None,
        checking_id: Optional[str] = None,
        fee_msat: Optional[int] = None,
        preimage: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        self.ok = ok
        self.checking_id = checking_id
        self.fee_msat = fee_msat
        self.preimage = preimage
        self.error_message = error_message


class PaymentStatus:
    """Status of a payment."""
    
    def __init__(
        self,
        paid: bool = False,
        pending: bool = False,
        failed: bool = False,
        fee_msat: Optional[int] = None,
    ):
        self.paid = paid
        self.pending = pending
        self.failed = failed
        self.fee_msat = fee_msat

    @property
    def success(self) -> bool:
        return self.paid


class PaymentPendingStatus(PaymentStatus):
    """Payment is pending."""
    
    def __init__(self):
        super().__init__(pending=True)


class PaymentSuccessStatus(PaymentStatus):
    """Payment was successful."""
    
    def __init__(self, fee_msat: Optional[int] = None):
        super().__init__(paid=True, fee_msat=fee_msat)


class PaymentFailedStatus(PaymentStatus):
    """Payment failed."""
    
    def __init__(self):
        super().__init__(failed=True)


class TaprootWalletExtension:
    """
    Wallet implementation for Taproot Assets.
    This wallet interfaces with a Taproot Assets daemon (tapd) to provide
    functionality for managing and transacting with Taproot Assets.
    """

    def __init__(self):
        """Initialize the Taproot Assets wallet."""
        self.settings = None
        self.channel = None
        self.stub = None
        self.ln_channel = None
        self.ln_stub = None
        self.tap_channel = None
        self.tapchannel_stub = None
    
    async def _init_connection(self):
        """Initialize the connection to tapd."""
        import os
        import grpc
        import grpc.aio
        
        if self.stub:
            return
        
        # Get settings from database
        from ..crud import db
        async with db.connect() as conn:
            self.settings = await get_or_create_settings(conn)
        
        # Read TLS certificate
        try:
            with open(self.settings.tapd_tls_cert_path, 'rb') as f:
                cert = f.read()
        except Exception as e:
            raise Exception(f"Failed to read TLS cert from {self.settings.tapd_tls_cert_path}: {str(e)}")

        # Read Taproot macaroon
        if self.settings.tapd_macaroon_hex:
            # Use the hex-encoded macaroon from settings
            macaroon = self.settings.tapd_macaroon_hex
        else:
            try:
                with open(self.settings.tapd_macaroon_path, 'rb') as f:
                    macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Taproot macaroon from {self.settings.tapd_macaroon_path}: {str(e)}")
            
        # Read Lightning macaroon (for invoice creation)
        if self.settings.lnd_macaroon_hex:
            # Use the hex-encoded macaroon from settings
            ln_macaroon = self.settings.lnd_macaroon_hex
        else:
            try:
                with open(self.settings.lnd_macaroon_path, 'rb') as f:
                    ln_macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Lightning macaroon from {self.settings.lnd_macaroon_path}: {str(e)}")

        # Setup gRPC auth credentials for Taproot
        credentials = grpc.ssl_channel_credentials(cert)
        auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", macaroon)], None)
        )
        combined_creds = grpc.composite_channel_credentials(
            credentials, auth_creds
        )

        # Setup gRPC auth credentials for Lightning
        ln_auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", ln_macaroon)], None)
        )
        ln_combined_creds = grpc.composite_channel_credentials(
            credentials, ln_auth_creds
        )

        # Create async gRPC channels
        self.channel = grpc.aio.secure_channel(self.settings.tapd_host, combined_creds)
        self.stub = create_taprootassets_client(self.channel)
        
        # Create Lightning gRPC channel for invoice creation
        self.ln_channel = grpc.aio.secure_channel(self.settings.tapd_host, ln_combined_creds)
        self.ln_stub = create_lightning_client(self.ln_channel)
        
        # Create TaprootAssetChannels gRPC channel for asset invoice creation
        self.tap_channel = grpc.aio.secure_channel(self.settings.tapd_host, combined_creds)
        self.tapchannel_stub = create_tapchannel_client(self.tap_channel)

    async def cleanup(self):
        """Close any open connections."""
        if self.channel:
            await self.channel.close()
        if self.ln_channel:
            await self.ln_channel.close()
        if self.tap_channel:
            await self.tap_channel.close()

    async def list_assets(self) -> List[Dict[str, Any]]:
        """List all Taproot Assets."""
        await self._init_connection()
        
        try:
            # Get all assets from tapd
            from .taproot_adapter import taprootassets_pb2
            
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
                        "genesis_point": "",
                        "meta_hash": "",
                        "version": "0",
                        "is_spent": False,
                        "script_key": "",
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
            raise Exception(f"Failed to list assets: {str(e)}")
        finally:
            await self.cleanup()
            
    async def list_channel_assets(self) -> List[Dict[str, Any]]:
        """
        List all Lightning channels with Taproot Assets.
        
        This method retrieves all Lightning channels and extracts Taproot asset information
        from channels with commitment type 4 or 6 (Taproot overlay).
        
        Returns:
            A list of dictionaries containing channel and asset information.
        """
        await self._init_connection()
        
        try:
            # Call the LND ListChannels endpoint
            from .taproot_adapter import lightning_pb2
            
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
                            import json
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
            logger.error(f"Error in list_channel_assets: {e}")
            raise Exception(f"Failed to list channel assets: {str(e)}")
        finally:
            await self.cleanup()

    async def create_invoice(
        self,
        amount: int,
        memo: Optional[str] = None,
        description_hash: Optional[bytes] = None,
        unhashed_description: Optional[bytes] = None,
        expiry: Optional[int] = None,
        **kwargs,
    ) -> InvoiceResponse:
        """
        Create an invoice for a Taproot Asset transfer.
        
        Args:
            amount: Amount of the asset to transfer
            memo: Optional description for the invoice
            description_hash: Optional hash of the description
            unhashed_description: Optional unhashed description
            expiry: Optional expiry time in seconds
            **kwargs: Additional parameters including:
                - asset_id: ID of the Taproot Asset (required)
        
        Returns:
            InvoiceResponse: Contains payment hash and payment request
        """
        await self._init_connection()
        
        # Extract asset_id from kwargs
        asset_id = kwargs.get("asset_id")
        
        if not asset_id:
            logger.warning("Missing asset_id parameter in create_invoice")
            return InvoiceResponse(False, None, None, "Missing asset_id parameter", None)
        
        try:
            # Create the invoice
            try:
                invoice_result = await self.create_asset_invoice(
                    memo=memo or "Taproot Asset Transfer",
                    asset_id=asset_id,
                    asset_amount=amount
                )
            except Exception as e:
                logger.warning(f"Error in create_asset_invoice: {e}")
                raise
            
            # Extract the payment hash and payment request
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]
            
            # Helper function to ensure all values are JSON serializable
            def ensure_serializable(obj):
                """Recursively convert an object to JSON serializable types."""
                import json
                if isinstance(obj, dict):
                    return {k: ensure_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [ensure_serializable(item) for item in obj]
                elif isinstance(obj, (str, int, float, bool, type(None))):
                    return obj
                elif hasattr(obj, '__dict__'):
                    # Convert custom objects to dict
                    return ensure_serializable(obj.__dict__)
                else:
                    # Convert anything else to string
                    return str(obj)
            
            # Store the accepted_buy_quote in the extra data for later use
            # This will be needed when processing the payment
            extra = {
                "type": "taproot_asset",
                "asset_id": asset_id,
                "asset_amount": amount
            }
            
            # Only add buy_quote if it exists and is not empty
            if invoice_result.get("accepted_buy_quote"):
                # Store the buy quote in the extra data
                extra["buy_quote"] = ensure_serializable(invoice_result.get("accepted_buy_quote"))
            
            # Return the invoice response
            return InvoiceResponse(
                ok=True,
                payment_hash=payment_hash,
                payment_request=payment_request,
                extra=extra
            )
        except Exception as e:
            logger.error(f"Failed to create invoice: {str(e)}")
            return InvoiceResponse(
                ok=False,
                error_message=f"Failed to create invoice: {str(e)}"
            )
        finally:
            await self.cleanup()
    
    async def create_asset_invoice(
        self,
        memo: str,
        asset_id: str,
        asset_amount: int,
        expiry: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create an invoice for a Taproot Asset transfer.
        
        This method calls the tapd API to create an invoice for a Taproot Asset transfer.
        
        Args:
            memo: Description for the invoice
            asset_id: ID of the Taproot Asset
            asset_amount: Amount of the asset to transfer
            expiry: Optional expiry time in seconds
        
        Returns:
            Dict containing the invoice result and accepted buy quote
        """
        await self._init_connection()
        
        try:
            # Import the necessary protobuf definitions
            from .taproot_adapter import taprootassets_pb2
            
            # Create the request
            request = taprootassets_pb2.CreateInvoiceRequest(
                asset_id=bytes.fromhex(asset_id),
                amount=asset_amount,
                memo=memo,
                expiry_seconds=expiry or 3600
            )
            
            # Call the API
            response = await self.stub.CreateInvoice(request, timeout=10)
            
            # Extract the invoice result
            invoice_result = {
                "r_hash": response.r_hash.hex(),
                "payment_request": response.payment_request,
                "memo": response.memo,
                "value": response.value,
                "expiry": response.expiry,
                "cltv_expiry": response.cltv_expiry,
                "timestamp": response.timestamp,
                "features": {k: v for k, v in response.features.items()},
                "payment_addr": response.payment_addr.hex(),
                "add_index": response.add_index,
                "state": response.state,
                "htlcs": [{
                    "chan_id": htlc.chan_id,
                    "htlc_index": htlc.htlc_index,
                    "amt_msat": htlc.amt_msat,
                    "accept_height": htlc.accept_height,
                    "accept_time": htlc.accept_time,
                    "resolve_time": htlc.resolve_time,
                    "expiry_height": htlc.expiry_height,
                    "state": htlc.state,
                    "custom_records": {k: v.hex() for k, v in htlc.custom_records.items()},
                    "mpp_total_amt_msat": htlc.mpp_total_amt_msat,
                } for htlc in response.htlcs],
                "amt_paid_msat": response.amt_paid_msat,
                "amt_paid_sat": response.amt_paid_sat,
                "creation_date": response.creation_date,
                "settle_date": response.settle_date,
                "is_keysend": response.is_keysend,
                "is_amp": response.is_amp,
                "amp_invoice_state": {k: v for k, v in response.amp_invoice_state.items()},
            }
            
            # Extract the accepted buy quote if present
            accepted_buy_quote = None
            if hasattr(response, "accepted_buy_quote") and response.accepted_buy_quote:
                accepted_buy_quote = {
                    "asset_id": response.accepted_buy_quote.asset_id.hex(),
                    "asset_amount": response.accepted_buy_quote.asset_amount,
                    "fee_rate_basis_points": response.accepted_buy_quote.fee_rate_basis_points,
                    "quote_id": response.accepted_buy_quote.quote_id.hex(),
                    "quote_expiry": response.accepted_buy_quote.quote_expiry,
                    "quote_signature": response.accepted_buy_quote.quote_signature.hex(),
                    "price_oracle_id": response.accepted_buy_quote.price_oracle_id.hex(),
                    "price_oracle_params": {
                        "asset_id": response.accepted_buy_quote.price_oracle_params.asset_id.hex(),
                        "price_per_unit": response.accepted_buy_quote.price_oracle_params.price_per_unit,
                        "timestamp": response.accepted_buy_quote.price_oracle_params.timestamp,
                        "signature": response.accepted_buy_quote.price_oracle_params.signature.hex(),
                    },
                }
            
            return {
                "invoice_result": invoice_result,
                "accepted_buy_quote": accepted_buy_quote
            }
        except Exception as e:
            logger.error(f"Failed to create asset invoice: {str(e)}")
            raise Exception(f"Failed to create asset invoice: {str(e)}")
        finally:
            await self.cleanup()
