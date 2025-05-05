import os
import time
import hashlib
import asyncio
from typing import Optional, Dict, Any, List
import grpc
import grpc.aio
import json
import base64
from lnbits import bolt11

# Import the adapter module for Taproot Asset gRPC interfaces
from .taproot_adapter import (
    taprootassets_pb2,
    rfq_pb2,
    rfq_pb2_grpc,
    tapchannel_pb2,
    lightning_pb2,
    invoices_pb2,
    create_taprootassets_client,
    create_tapchannel_client,
    create_lightning_client,
    create_invoices_client
)

# Import the manager modules
from .taproot_assets import TaprootAssetManager
from .taproot_invoices import TaprootInvoiceManager
from .taproot_payments import TaprootPaymentManager
from .taproot_transfers import TaprootTransferManager

# Import settlement service
from ..settlement_service import SettlementService

# Import logging utilities
from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, NODE, LogContext
)
from ..error_utils import ErrorContext, TaprootAssetError

class TaprootAssetsNodeExtension:
    """
    Implementation of Taproot Assets node functionality for the extension.
    This mirrors the core TaprootAssetsNode class.
    """
    # Class-level cache to store preimages with expiry times
    _preimage_cache = {}
    
    # Default expiry time for preimages (24 hours)
    DEFAULT_PREIMAGE_EXPIRY = 86400

    def _store_preimage(self, payment_hash: str, preimage: str):
        """
        Store a preimage for a given payment hash with expiry time.
        
        Args:
            payment_hash: The payment hash
            preimage: The preimage corresponding to the payment hash
        """
        expiry = int(time.time()) + self.DEFAULT_PREIMAGE_EXPIRY
        self.__class__._preimage_cache[payment_hash] = {
            "preimage": preimage,
            "expiry": expiry
        }
        log_debug(NODE, f"Stored preimage for payment hash: {payment_hash[:8]}...")

    def _get_preimage(self, payment_hash: str) -> Optional[str]:
        """
        Retrieve a preimage for a given payment hash, checking expiry.
        
        Args:
            payment_hash: The payment hash to look up
            
        Returns:
            str: The preimage if found and not expired, None otherwise
        """
        entry = self.__class__._preimage_cache.get(payment_hash)
        
        # No entry found
        if not entry:
            log_debug(NODE, f"No preimage found for payment hash: {payment_hash[:8]}...")
            return None
            
        # Handle legacy plain preimage strings (backward compatibility)
        if isinstance(entry, str):
            log_debug(NODE, f"Found legacy preimage for payment hash: {payment_hash[:8]}...")
            return entry
            
        # Check for expiry if it's a dict with expiry
        if isinstance(entry, dict):
            # If expired, remove and return None
            if entry.get("expiry") and entry["expiry"] < int(time.time()):
                log_debug(NODE, f"Preimage expired for payment hash: {payment_hash[:8]}...")
                del self.__class__._preimage_cache[payment_hash]
                return None
                
            # Return the preimage
            log_debug(NODE, f"Found valid preimage for payment hash: {payment_hash[:8]}...")
            return entry.get("preimage")
            
        # Unexpected entry type
        log_warning(NODE, f"Unexpected preimage cache entry type for payment hash: {payment_hash[:8]}...")
        return None

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

        log_debug(NODE, "Initializing TaprootAssetsNodeExtension")
        
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
            log_debug(NODE, f"Reading TLS cert from {tls_cert_path}")
            with open(tls_cert_path, 'rb') as f:
                self.cert = f.read()
            log_debug(NODE, "Successfully read TLS certificate")
        except Exception as e:
            log_error(NODE, f"Failed to read TLS cert from {tls_cert_path}: {str(e)}")
            raise TaprootAssetError(f"Failed to read TLS cert from {tls_cert_path}: {str(e)}")

        # Read Taproot macaroon
        if tapd_macaroon_hex:
            log_debug(NODE, "Using provided tapd_macaroon_hex")
            self.macaroon = tapd_macaroon_hex
        else:
            try:
                log_debug(NODE, f"Reading Taproot macaroon from {macaroon_path}")
                with open(macaroon_path, 'rb') as f:
                    self.macaroon = f.read().hex()
                log_debug(NODE, "Successfully read Taproot macaroon")
            except Exception as e:
                log_error(NODE, f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")
                raise TaprootAssetError(f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")

        # Read Lightning macaroon
        if ln_macaroon_hex:
            log_debug(NODE, "Using provided ln_macaroon_hex")
            self.ln_macaroon = ln_macaroon_hex
        else:
            try:
                log_debug(NODE, f"Reading Lightning macaroon from {ln_macaroon_path}")
                with open(ln_macaroon_path, 'rb') as f:
                    self.ln_macaroon = f.read().hex()
                log_debug(NODE, "Successfully read Lightning macaroon")
            except Exception as e:
                log_error(NODE, f"Failed to read Lightning macaroon from {ln_macaroon_path}: {str(e)}")
                raise TaprootAssetError(f"Failed to read Lightning macaroon from {ln_macaroon_path}: {str(e)}")

        log_debug(NODE, "Setting up gRPC credentials")
        # Setup gRPC credentials for Taproot
        self.credentials = grpc.ssl_channel_credentials(self.cert)
        self.auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.macaroon)], None)
        )
        self.combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.auth_creds
        )

        # Setup gRPC credentials for Lightning
        self.ln_auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.ln_macaroon)], None)
        )
        self.ln_combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.ln_auth_creds
        )

        log_debug(NODE, f"Creating gRPC channels to {self.host}")
        # Create gRPC channels
        self.channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        self.stub = create_taprootassets_client(self.channel)

        # Create Lightning gRPC channel
        self.ln_channel = grpc.aio.secure_channel(self.host, self.ln_combined_creds)
        self.ln_stub = create_lightning_client(self.ln_channel)
        self.invoices_stub = create_invoices_client(self.ln_channel)

        # Create TaprootAssetChannels gRPC channel
        self.tap_channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        self.tapchannel_stub = create_tapchannel_client(self.tap_channel)

        log_debug(NODE, "Initializing managers")
        # Initialize managers
        self.asset_manager = TaprootAssetManager(self)
        self.invoice_manager = TaprootInvoiceManager(self)
        self.payment_manager = TaprootPaymentManager(self)
        self.transfer_manager = TaprootTransferManager(self)

        # Start monitoring asset transfers (if not already running)
        if not TaprootTransferManager._is_monitoring:
            log_info(NODE, "Starting asset transfer monitoring")
            self.monitoring_task = asyncio.create_task(self.transfer_manager.monitor_asset_transfers())
        else:
            log_debug(NODE, "Asset transfer monitoring already active")

    def _protobuf_to_dict(self, pb_obj):
        """Convert a protobuf object to a JSON-serializable dict."""
        if pb_obj is None:
            return None

        result = {}
        for field_name in pb_obj.DESCRIPTOR.fields_by_name:
            value = getattr(pb_obj, field_name)
            
            # Convert bytes to hex strings
            if isinstance(value, bytes):
                result[field_name] = value.hex()
            # Handle nested messages
            elif hasattr(value, 'DESCRIPTOR'):
                nested_dict = self._protobuf_to_dict(value)
                if nested_dict is not None:
                    result[field_name] = nested_dict
            # Handle lists
            elif isinstance(value, (list, tuple)):
                result[field_name] = [
                    self._protobuf_to_dict(item) if hasattr(item, 'DESCRIPTOR') else item
                    for item in value
                ]
            # Handle large integers
            elif isinstance(value, int) and value > 2**53 - 1:
                result[field_name] = str(value)
            # Special handling for active status in channel
            elif field_name == 'active':
                # Make sure active status is explicitly set to True or False
                result[field_name] = bool(value)
            # Handle other values
            else:
                result[field_name] = value
                
        return result

    # Delegate methods to the appropriate managers
    async def list_assets(self) -> List[Dict[str, Any]]:
        """List all Taproot Assets."""
        with LogContext(NODE, "listing assets", log_level="debug"):
            return await self.asset_manager.list_assets()

    async def list_channel_assets(self) -> List[Dict[str, Any]]:
        """List all Lightning channels with Taproot Assets."""
        with LogContext(NODE, "listing channel assets", log_level="debug"):
            return await self.asset_manager.list_channel_assets()

    async def create_asset_invoice(
        self,
        memo: str,
        asset_id: str,
        asset_amount: int,
        expiry: Optional[int] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create an invoice for a Taproot Asset transfer."""
        with LogContext(NODE, f"creating asset invoice for {asset_id[:8]}...", log_level="info"):
            return await self.invoice_manager.create_asset_invoice(
                memo, asset_id, asset_amount, expiry, peer_pubkey
            )

    async def pay_asset_invoice(
        self,
        payment_request: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pay a Taproot Asset invoice."""
        with LogContext(NODE, "paying asset invoice", log_level="info"):
            return await self.payment_manager.pay_asset_invoice(
                payment_request, fee_limit_sats, asset_id, peer_pubkey
            )

    async def update_after_payment(
        self,
        payment_request: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update Taproot Assets after a payment has been made through the LNbits wallet."""
        with LogContext(NODE, f"updating after payment {payment_hash[:8]}...", log_level="info"):
            return await self.payment_manager.update_after_payment(
                payment_request, payment_hash, fee_limit_sats, asset_id
            )

    async def monitor_invoice(self, payment_hash: str):
        """
        Monitor a specific invoice for state changes.
        
        This method delegates to the transfer_manager's implementation
        which includes direct settlement logic.
        """
        with LogContext(NODE, f"monitoring invoice {payment_hash[:8]}...", log_level="debug"):
            return await self.transfer_manager.monitor_invoice(payment_hash)

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
        with LogContext(NODE, f"manually settling invoice {payment_hash[:8]}...", log_level="info"):
            return await self.transfer_manager.manually_settle_invoice(payment_hash, script_key)

    async def close(self):
        """Close the gRPC channels."""
        log_debug(NODE, "Closing gRPC channels")
        await self.channel.close()
        await self.ln_channel.close()
        await self.tap_channel.close()
        log_debug(NODE, "gRPC channels closed")
