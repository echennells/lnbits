import os
import time
import hashlib
import asyncio
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

class TaprootAssetsNodeExtension:
    """
    Implementation of Taproot Assets node functionality for the extension.
    This mirrors the core TaprootAssetsNode class.
    """
    # Class-level cache to store preimages
    _preimage_cache = {}

    def _store_preimage(self, payment_hash: str, preimage: str):
        """Store a preimage for a given payment hash."""
        self.__class__._preimage_cache[payment_hash] = preimage
        logger.debug(f"Stored preimage for payment hash: {payment_hash}")

    def _get_preimage(self, payment_hash: str) -> Optional[str]:
        """Retrieve a preimage for a given payment hash."""
        preimage = self.__class__._preimage_cache.get(payment_hash)
        if not preimage:
            logger.debug(f"No preimage found for payment hash: {payment_hash}")
        return preimage

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
            self.macaroon = tapd_macaroon_hex
        else:
            try:
                with open(macaroon_path, 'rb') as f:
                    self.macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")

        # Read Lightning macaroon
        if ln_macaroon_hex:
            self.ln_macaroon = ln_macaroon_hex
        else:
            try:
                with open(ln_macaroon_path, 'rb') as f:
                    self.ln_macaroon = f.read().hex()
            except Exception as e:
                raise Exception(f"Failed to read Lightning macaroon from {ln_macaroon_path}: {str(e)}")

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

        # Initialize managers
        self.asset_manager = TaprootAssetManager(self)
        self.invoice_manager = TaprootInvoiceManager(self)
        self.payment_manager = TaprootPaymentManager(self)
        self.transfer_manager = TaprootTransferManager(self)

        # Start monitoring asset transfers
        logger.info("Starting asset transfer monitoring")
        self.monitoring_task = asyncio.create_task(self.transfer_manager.monitor_asset_transfers())

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
            # Handle other values
            else:
                result[field_name] = value
                
        return result

    # Delegate methods to the appropriate managers
    async def list_assets(self) -> List[Dict[str, Any]]:
        """List all Taproot Assets."""
        return await self.asset_manager.list_assets()

    async def list_channel_assets(self) -> List[Dict[str, Any]]:
        """List all Lightning channels with Taproot Assets."""
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
        return await self.payment_manager.update_after_payment(
            payment_request, payment_hash, fee_limit_sats, asset_id
        )

    async def monitor_invoice(self, payment_hash: str):
        """
        Monitor a specific invoice for state changes.
        
        This method delegates to the transfer_manager's implementation
        which includes direct settlement logic.
        """
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
        return await self.transfer_manager.manually_settle_invoice(payment_hash, script_key)

    async def close(self):
        """Close the gRPC channels."""
        await self.channel.close()
        await self.ln_channel.close()
        await self.tap_channel.close()
