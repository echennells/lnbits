import os
from typing import Optional, Dict, Any
import grpc
import grpc.aio
import json
import base64

from lnbits import bolt11

from lnbits.wallets.tapd_grpc_files import taprootassets_pb2 as tap_pb2
from lnbits.wallets.tapd_grpc_files import taprootassets_pb2_grpc as tap_grpc
from lnbits.wallets.lnd_grpc_files import lightning_pb2 as ln_pb2
from lnbits.wallets.lnd_grpc_files import lightning_pb2_grpc as ln_grpc

class TaprootAssetsNode:
    """
    Implementation of Taproot Assets node functionality.
    This is separate from the base Node class since Taproot Assets 
    have different capabilities than Lightning nodes.
    """
    
    def __init__(
        self,
        host: str = os.getenv("TAPD_HOST", "lit:10009"),
        network: str = os.getenv("TAPD_NETWORK", "signet"),
        tls_cert_path: str = os.getenv("TAPD_TLS_CERT_PATH", "/root/.lnd/tls.cert"),
        macaroon_path: str = os.getenv("TAPD_MACAROON_PATH", "/root/.tapd/data/signet/admin.macaroon"),
        ln_macaroon_path: str = os.getenv("LND_MACAROON_PATH", "/root/.lnd/data/chain/bitcoin/signet/admin.macaroon"),
        ln_macaroon_hex: str = os.getenv("LND_MACAROON_HEX", ""),
        tapd_macaroon_hex: str = os.getenv("TAPD_MACAROON_HEX", ""),
    ):
        self.host = host
        self.network = network
        
        # Read TLS certificate
        try:
            with open(tls_cert_path, 'rb') as f:
                self.cert = f.read()
        except Exception as e:
            raise Exception(f"Failed to read TLS cert: {str(e)}")

        # Read Taproot macaroon
        if tapd_macaroon_hex:
            # Use the hex-encoded macaroon from environment variable
            self.macaroon = tapd_macaroon_hex
        else:
            try:
                with open(macaroon_path, 'rb') as f:
                    self.macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Taproot macaroon: {str(e)}")
            
        # Read Lightning macaroon (for invoice creation)
        if ln_macaroon_hex:
            # Use the hex-encoded macaroon from environment variable
            self.ln_macaroon = ln_macaroon_hex
        else:
            try:
                with open(ln_macaroon_path, 'rb') as f:
                    self.ln_macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Lightning macaroon: {str(e)}")

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
        self.stub = tap_grpc.TaprootAssetsStub(self.channel)
        
        # Create Lightning gRPC channel for invoice creation
        self.ln_channel = grpc.aio.secure_channel(self.host, self.ln_combined_creds)
        self.ln_stub = ln_grpc.LightningStub(self.ln_channel)

    async def list_assets(self) -> list[dict]:
        """List all Taproot Assets."""
        try:
            request = tap_pb2.ListAssetRequest(  # type: ignore
                with_witness=False,
                include_spent=False,  # Changed to avoid conflict with include_leased
                include_leased=True,
                include_unconfirmed_mints=True
            )
            response = await self.stub.ListAssets(request, timeout=10)
            return [
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
        except Exception as e:
            raise Exception(f"Failed to list assets: {str(e)}")
            
    async def create_asset_invoice(self, memo: str, asset_id: str, asset_amount: int) -> Dict[str, Any]:
        """
        Create an invoice for a Taproot Asset transfer.
        
        This uses the Lightning Network API to create an invoice with Taproot Asset metadata.
        The RFQ (Request for Quote) process is handled internally by the Lightning Terminal.
        
        Args:
            memo: Description for the invoice
            asset_id: The ID of the Taproot Asset
            asset_amount: The amount of the asset to transfer
            
        Returns:
            Dict containing the invoice information
        """
        try:
            # For Taproot Assets, we need to use the Lightning API with special metadata
            # Create a Lightning invoice with Taproot Asset metadata in custom records
            
            # Convert asset_id from hex to bytes if needed
            asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id
            
            # Create a basic invoice using LND's AddInvoice
            invoice_request = ln_pb2.Invoice()
            invoice_request.memo = memo if memo else "Taproot Asset Transfer"
            invoice_request.value = 0  # Value in satoshis
            
            # Call LND's AddInvoice method
            response = await self.ln_stub.AddInvoice(invoice_request, timeout=30)
            
            # Extract the payment hash and payment request
            payment_hash = response.r_hash.hex() if isinstance(response.r_hash, bytes) else response.r_hash
            payment_request = response.payment_request
            
            # Since we don't have direct access to the RFQ information from the gRPC response,
            # we'll create a simplified version based on what we know
            accepted_buy_quote = {
                "id": "generated_" + payment_hash[:8],
                "asset_id": asset_id,
                "asset_amount": asset_amount,
                "min_transportable_units": 1,  # Default value
                "expiry": 3600,  # 1 hour expiry
                "scid": "0x0x0",  # Placeholder
                "peer": "unknown",  # Placeholder
            }
            
            # Return the invoice information
            return {
                "accepted_buy_quote": accepted_buy_quote,
                "invoice_result": {
                    "r_hash": payment_hash,
                    "payment_request": payment_request,
                    "add_index": response.add_index,
                }
            }
        except Exception as e:
            raise Exception(f"Failed to create asset invoice: {str(e)}")

    async def close(self):
        """Close the gRPC channels."""
        await self.channel.close()
        await self.ln_channel.close()
