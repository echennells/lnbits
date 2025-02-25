import os
from typing import Optional
import grpc
import grpc.aio

from lnbits.wallets.tapd_grpc_files import taprootassets_pb2 as tap_pb2
from lnbits.wallets.tapd_grpc_files import taprootassets_pb2_grpc as tap_grpc

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
    ):
        self.host = host
        self.network = network
        
        # Read TLS certificate
        try:
            with open(tls_cert_path, 'rb') as f:
                self.cert = f.read()
        except Exception as e:
            raise Exception(f"Failed to read TLS cert: {str(e)}")

        # Read macaroon
        try:
            with open(macaroon_path, 'rb') as f:
                self.macaroon = f.read().hex()
        except Exception as e:
            raise Exception(f"Failed to read macaroon: {str(e)}")

        # Setup gRPC auth credentials
        self.credentials = grpc.ssl_channel_credentials(self.cert)
        self.auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.macaroon)], None)
        )
        self.combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.auth_creds
        )

        # Create async gRPC channel
        self.channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        self.stub = tap_grpc.TaprootAssetsStub(self.channel)

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

    async def close(self):
        """Close the gRPC channel."""
        await self.channel.close()
