import asyncio
from typing import Optional, Dict, Any
import grpc
import grpc.aio

from ..logging_utils import log_debug, log_info, log_warning, log_error, PARSER, LogContext
from ..error_utils import TaprootAssetError
from ..tapd_settings import taproot_settings

# Import the adapter module for Taproot Asset gRPC interfaces
from .taproot_adapter import (
    tapchannel_pb2,
    create_taprootassets_client,
    create_tapchannel_client
)

class TaprootParserClient:
    """
    Singleton client for parsing Taproot Asset invoices.
    This class provides a shared connection to the Taproot Assets daemon
    specifically for invoice parsing operations, avoiding connection leaks.
    """
    _instance = None
    _initialized = False
    
    @classmethod
    def get_instance(cls):
        """
        Get or create the singleton instance.
        
        Returns:
            The singleton TaprootParserClient instance
        """
        if cls._instance is None:
            cls._instance = cls()
            log_info(PARSER, "TaprootParserClient initialized")
        return cls._instance

    def __init__(self):
        """
        Initialize the parser client.
        This should only be called once through get_instance().
        """
        self.host = None
        self.channel = None
        self.tapchannel_stub = None
        self.assets = []
        self.last_assets_fetch = 0
        self._initialized = False
        
    async def ensure_initialized(self):
        """
        Ensure the client is initialized with proper connections.
        """
        if self._initialized:
            return
            
        with LogContext(PARSER, "Initializing parser client"):
            # Get settings
            self.host = taproot_settings.tapd_host
            tls_cert_path = taproot_settings.tapd_tls_cert_path
            tapd_macaroon_hex = taproot_settings.tapd_macaroon_hex
            macaroon_path = taproot_settings.tapd_macaroon_path
            
            # Read TLS certificate
            try:
                log_debug(PARSER, f"Reading TLS cert from {tls_cert_path}")
                with open(tls_cert_path, 'rb') as f:
                    self.cert = f.read()
                log_debug(PARSER, "Successfully read TLS certificate")
            except Exception as e:
                log_error(PARSER, f"Failed to read TLS cert from {tls_cert_path}: {str(e)}")
                raise TaprootAssetError(f"Failed to read TLS cert from {tls_cert_path}: {str(e)}")

            # Read Taproot macaroon
            if tapd_macaroon_hex:
                log_debug(PARSER, "Using provided tapd_macaroon_hex")
                self.macaroon = tapd_macaroon_hex
            else:
                try:
                    log_debug(PARSER, f"Reading Taproot macaroon from {macaroon_path}")
                    with open(macaroon_path, 'rb') as f:
                        self.macaroon = f.read().hex()
                    log_debug(PARSER, "Successfully read Taproot macaroon")
                except Exception as e:
                    log_error(PARSER, f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")
                    raise TaprootAssetError(f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")

            log_debug(PARSER, "Setting up gRPC credentials")
            # Setup gRPC credentials for Taproot
            self.credentials = grpc.ssl_channel_credentials(self.cert)
            self.auth_creds = grpc.metadata_call_credentials(
                lambda context, callback: callback([("macaroon", self.macaroon)], None)
            )
            self.combined_creds = grpc.composite_channel_credentials(
                self.credentials, self.auth_creds
            )

            log_debug(PARSER, f"Creating gRPC channels to {self.host}")
            # Create gRPC channels
            self.channel = grpc.aio.secure_channel(self.host, self.combined_creds)
            self.stub = create_taprootassets_client(self.channel)
            
            # Create TaprootAssetChannels gRPC channel
            self.tapchannel_stub = create_tapchannel_client(self.channel)
            
            self._initialized = True
            log_info(PARSER, "Parser client initialized successfully")
    
    async def list_assets(self, force_refresh=False):
        """
        List all Taproot Assets.
        Delegates to TaprootAssetManager for the actual retrieval.
        
        Args:
            force_refresh: Force a refresh of the assets list
            
        Returns:
            List of assets
        """
        await self.ensure_initialized()
        
        # Create an asset manager instance if needed
        if not hasattr(self, 'asset_manager'):
            from .taproot_assets import TaprootAssetManager
            self.asset_manager = TaprootAssetManager(self)
        
        # Delegate to asset manager with caching controlled by force_refresh parameter
        assets = await self.asset_manager.list_assets(force_refresh=force_refresh)
        
        # Store the assets in the instance for backward compatibility
        self.assets = assets
        
        # Update last fetch time for backward compatibility
        import time
        self.last_assets_fetch = time.time()
        
        log_debug(PARSER, f"Retrieved {len(assets)} assets via asset manager")
        return assets
    
    async def decode_asset_pay_req(self, asset_id: str, payment_request: str) -> Dict[str, Any]:
        """
        Decode an asset payment request.
        
        Args:
            asset_id: The asset ID to use for decoding
            payment_request: The payment request to decode
            
        Returns:
            Dict containing the decoded payment request
        """
        await self.ensure_initialized()
        
        try:
            # Create the request
            request = tapchannel_pb2.AssetPayReq(
                asset_id=bytes.fromhex(asset_id),
                pay_req_string=payment_request
            )
            
            # Call the DecodeAssetPayReq RPC
            response = await self.tapchannel_stub.DecodeAssetPayReq(request)
            
            # Convert to dict
            result = {}
            for field in ['asset_id', 'asset_amount', 'payment_addr', 'payment_hash', 'timestamp', 'expiry', 'description']:
                if hasattr(response, field):
                    value = getattr(response, field)
                    if isinstance(value, bytes):
                        result[field] = value.hex()
                    else:
                        result[field] = value
            
            return result
        except Exception as e:
            log_error(PARSER, f"Error decoding asset payment request: {str(e)}")
            raise
    
    async def close(self):
        """Close the gRPC channels."""
        if self._initialized and self.channel:
            log_debug(PARSER, "Closing gRPC channels")
            await self.channel.close()
            self._initialized = False
            log_debug(PARSER, "gRPC channels closed")
