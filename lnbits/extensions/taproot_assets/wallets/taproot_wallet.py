from typing import AsyncGenerator, Dict, List, Optional, Any, Coroutine, Union

from lnbits.settings import settings
from lnbits.wallets.base import Wallet, InvoiceResponse as BaseInvoiceResponse, PaymentResponse as BasePaymentResponse, PaymentStatus, StatusResponse, PaymentPendingStatus

from .taproot_node import TaprootAssetsNodeExtension
# Import from crud re-exports
from ..crud import (
    get_invoice_by_payment_hash
)
from ..tapd_settings import taproot_settings
from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, WALLET, LogContext
)
from ..error_utils import ErrorContext


class TaprootWalletExtension(Wallet):
    """
    Wallet implementation for Taproot Assets.
    This wallet interfaces with a Taproot Assets daemon (tapd) to provide
    low-level functionality for managing and transacting with Taproot Assets.
    
    This class focuses only on the direct interaction with the node and does not
    include business logic, which is handled by the service layer.
    """
    __node_cls__ = TaprootAssetsNodeExtension

    def __init__(self):
        """Initialize the Taproot Assets wallet."""
        super().__init__()
        self.initialized = False
        # For storing user and wallet info
        self.user: Optional[str] = None
        self.id: Optional[str] = None
        # Explicitly add the node attribute with proper typing
        self.node: Optional[TaprootAssetsNodeExtension] = None  # Will be set by the factory

    async def ensure_initialized(self):
        """Ensure the wallet is initialized."""
        if not self.initialized:
            if self.node is None:
                raise ValueError("Node not initialized. The wallet must be initialized with a node instance.")
            self.initialized = True

    async def cleanup(self):
        """Close any open connections."""
        # This is a no-op for compatibility with the interface
        pass

    async def status(self) -> StatusResponse:
        """Get wallet status."""
        # Taproot Assets doesn't have a direct balance concept like Lightning
        # This is a placeholder implementation
        return StatusResponse(None, 0)

    async def get_invoice_status(self, checking_id: str) -> PaymentStatus:
        """Get invoice status."""
        # Placeholder implementation
        # In a real implementation, this would check the status of an invoice
        return PaymentPendingStatus()

    async def get_payment_status(self, checking_id: str) -> PaymentStatus:
        """Get payment status."""
        # Placeholder implementation
        # In a real implementation, this would check the status of a payment
        return PaymentPendingStatus()

    async def pay_invoice(self, bolt11: str, fee_limit_msat: int) -> BasePaymentResponse:
        """Pay a Lightning invoice."""
        # Placeholder implementation
        # In a real implementation, this would pay a Lightning invoice
        return BasePaymentResponse(
            ok=False,
            error_message="pay_invoice not implemented for Taproot Assets"
        )

    async def list_assets(self) -> List[Dict[str, Any]]:
        """
        List all Taproot Assets - low-level node method.
        
        Returns:
            List[Dict[str, Any]]: Raw list of assets from node
        """
        with LogContext(WALLET, "listing assets"):
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            return await self.node.list_assets()

    async def get_raw_node_invoice(
        self,
        description: str,
        asset_id: str,
        asset_amount: int,
        expiry: Optional[int] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create an invoice for a Taproot Asset transfer at the node level.
        This is a low-level operation that directly interacts with the node.

        Args:
            description: Description for the invoice
            asset_id: The ID of the Taproot Asset
            asset_amount: The amount of the asset to transfer
            expiry: Optional expiry time in seconds
            peer_pubkey: Optional peer public key to specify which channel to use

        Returns:
            Dict containing the invoice information with accepted_buy_quote and invoice_result
        """
        with ErrorContext("get_raw_node_invoice", WALLET):
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            peer_info = f" with peer {peer_pubkey[:8]}..." if peer_pubkey else ""
            log_debug(WALLET, f"Creating raw node invoice for {asset_id[:8]}..., amount={asset_amount}{peer_info}")
            
            result = await self.node.create_asset_invoice(
                description=description,  # Now using description parameter
                asset_id=asset_id,
                asset_amount=asset_amount,
                expiry=expiry,
                peer_pubkey=peer_pubkey
            )
            
            log_debug(WALLET, f"Raw node invoice created successfully")
            return result

    async def create_invoice(
        self,
        amount: int,
        memo: Optional[str] = None,
        description_hash: Optional[bytes] = None,
        unhashed_description: Optional[bytes] = None,
        **kwargs,
    ) -> BaseInvoiceResponse:
        """
        Create an invoice for a Taproot Asset transfer.
        This method only handles the direct node interaction.
        
        Args:
            amount: Amount of the asset to transfer
            memo: Optional description for the invoice
            description_hash: Optional hash of the description
            unhashed_description: Optional unhashed description
            **kwargs: Additional parameters including:
                - asset_id: ID of the Taproot Asset (required)
                - peer_pubkey: Optional peer public key to specify which channel to use
                - expiry: Optional expiry time in seconds

        Returns:
            InvoiceResponse: Contains payment hash and payment request
        """
        await self.ensure_initialized()

        # Extract asset_id and other parameters from kwargs
        asset_id = kwargs.get("asset_id")
        expiry = kwargs.get("expiry")
        peer_pubkey = kwargs.get("peer_pubkey")
        
        if not asset_id:
            log_warning(WALLET, "Missing asset_id parameter in create_invoice")
            return BaseInvoiceResponse(False, None, None, "Missing asset_id parameter")

        try:
            # Create the invoice using the low-level method
            invoice_result = await self.get_raw_node_invoice(
                description=memo or "Taproot Asset Transfer",
                asset_id=asset_id,
                asset_amount=amount,
                expiry=expiry,
                peer_pubkey=peer_pubkey
            )

            # Extract payment details
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]

            return BaseInvoiceResponse(
                ok=True,
                checking_id=payment_hash,
                payment_request=payment_request,
                error_message=None
            )
        except Exception as e:
            log_error(WALLET, f"Failed to create invoice: {str(e)}")
            return BaseInvoiceResponse(
                ok=False,
                checking_id=None,
                payment_request=None,
                error_message=f"Failed to create invoice: {str(e)}"
            )
        finally:
            pass  # No cleanup needed

    async def send_raw_payment(
        self,
        payment_request: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Low-level method to send a payment to a Taproot Asset invoice.
        This method only performs the direct node interaction without business logic.
        
        Args:
            payment_request: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            asset_id: Optional ID of the Taproot Asset to use for payment
            peer_pubkey: Optional peer public key to specify which channel to use
            
        Returns:
            Dict[str, Any]: Raw payment result from the node
        """
        with ErrorContext("send_raw_payment", WALLET):
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")

            # Call the node's pay_asset_invoice method
            payment_result = await self.node.pay_asset_invoice(
                payment_request=payment_request,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id,
                peer_pubkey=peer_pubkey
            )
            
            # Store the asset_id in the node's cache if present
            payment_hash = payment_result.get("payment_hash")
            asset_id_to_store = payment_result.get("asset_id", asset_id)
            
            if payment_hash and asset_id_to_store:
                self.node._store_asset_id(payment_hash, asset_id_to_store)
                
            return payment_result

    async def pay_asset_invoice(
        self,
        invoice: str,
        fee_limit_sats: Optional[int] = None,
        peer_pubkey: Optional[str] = None,
        **kwargs,
    ) -> BasePaymentResponse:
        """
        Low-level method to pay a Taproot Asset invoice.
        This method only performs the direct node interaction.
        
        Args:
            invoice: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            peer_pubkey: Optional peer public key to specify which channel to use
            **kwargs: Additional parameters including:
                - asset_id: Optional ID of the Taproot Asset to use for payment
                
        Returns:
            BasePaymentResponse: Contains basic information about the payment
        """
        try:
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            
            # Extract asset_id from kwargs if provided
            asset_id = kwargs.get("asset_id")
            
            # Call the raw payment method
            payment_result = await self.send_raw_payment(
                payment_request=invoice,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id,
                peer_pubkey=peer_pubkey
            )

            # Extract payment details
            payment_hash = payment_result.get("payment_hash", "")
            preimage = payment_result.get("payment_preimage", "")
            fee_msat = payment_result.get("fee_sats", 0) * 1000  # Convert sats to msats
            
            # Create a simple response with just the payment information
            response = BasePaymentResponse(
                ok=True,
                checking_id=payment_hash,
                fee_msat=fee_msat,
                preimage=preimage,
                error_message=None
            )
            
            return response
        except Exception as e:
            log_error(WALLET, f"Failed to pay invoice: {str(e)}")
            return BasePaymentResponse(
                ok=False,
                checking_id=None,
                fee_msat=None,
                preimage=None,
                error_message=f"Failed to pay invoice: {str(e)}"
            )
        finally:
            pass  # No cleanup needed
