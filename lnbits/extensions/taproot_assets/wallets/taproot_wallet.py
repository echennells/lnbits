from typing import AsyncGenerator, Dict, List, Optional, Any, Coroutine, Union

from lnbits.settings import settings
from lnbits.wallets.base import Wallet, InvoiceResponse as BaseInvoiceResponse, PaymentResponse as BasePaymentResponse, PaymentStatus, StatusResponse, PaymentPendingStatus

from .taproot_node import TaprootAssetsNodeExtension
# Import from crud re-exports
from ..crud import (
    get_or_create_settings,
    get_invoice_by_payment_hash,
    is_self_payment
)
from ..tapd_settings import taproot_settings
from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, WALLET, LogContext
)
from ..error_utils import ErrorContext
from ..settlement_service import SettlementService


class TaprootWalletExtension(Wallet):
    """
    Wallet implementation for Taproot Assets.
    This wallet interfaces with a Taproot Assets daemon (tapd) to provide
    functionality for managing and transacting with Taproot Assets.
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
        """List all Taproot Assets."""
        with LogContext(WALLET, "listing assets"):
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            return await self.node.list_assets()

    async def manually_settle_invoice(
        self,
        payment_hash: str,
        script_key: Optional[str] = None,
    ) -> bool:
        """
        Manually settle a HODL invoice using the stored preimage.
        This can be used as a fallback if automatic settlement fails.

        Args:
            payment_hash: The payment hash of the invoice to settle
            script_key: Optional script key to use for lookup if payment hash is not found directly

        Returns:
            bool: True if settlement was successful, False otherwise
        """
        try:
            with LogContext(WALLET, f"manually settling invoice {payment_hash[:8]}..."):
                await self.ensure_initialized()
                if self.node is None:
                    raise ValueError("Node not initialized")
                
                # Use SettlementService for settlement
                success, _ = await SettlementService.settle_invoice(
                    payment_hash=payment_hash,
                    node=self.node,
                    is_internal=False,  # Default to external payment for manual settlement
                    is_self_payment=False,
                    user_id=self.user,
                    wallet_id=self.id
                )
                
                return success
        except Exception as e:
            log_error(WALLET, f"Error in manual settlement: {str(e)}")
            return False
        finally:
            await self.cleanup()

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
        
        if not asset_id:
            log_warning(WALLET, "Missing asset_id parameter in create_invoice")
            return BaseInvoiceResponse(False, None, None, "Missing asset_id parameter")

        try:
            # Get peer_pubkey from kwargs if provided
            peer_pubkey = kwargs.get("peer_pubkey")
            peer_info = f" with peer {peer_pubkey[:8]}..." if peer_pubkey else ""
            
            log_info(WALLET, f"Creating invoice for asset {asset_id[:8]}..., amount={amount}{peer_info}")
            
            # Create the invoice
            invoice_result = await self.create_asset_invoice(
                memo=memo or "Taproot Asset Transfer",
                asset_id=asset_id,
                asset_amount=amount,
                expiry=expiry,
                peer_pubkey=peer_pubkey
            )

            # Extract payment details
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]
            
            log_info(WALLET, f"Invoice created successfully, payment_hash={payment_hash[:8]}...")

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
            await self.cleanup()

    async def create_asset_invoice(
        self,
        memo: str,
        asset_id: str,
        asset_amount: int,
        expiry: Optional[int] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
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
            peer_pubkey: Optional peer public key to specify which channel to use

        Returns:
            Dict containing the invoice information with accepted_buy_quote and invoice_result
        """
        with ErrorContext("create_asset_invoice", WALLET):
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            peer_info = f" with peer {peer_pubkey[:8]}..." if peer_pubkey else ""
            log_debug(WALLET, f"Creating asset invoice for {asset_id[:8]}..., amount={asset_amount}{peer_info}")
            
            result = await self.node.create_asset_invoice(
                memo=memo,
                asset_id=asset_id,
                asset_amount=asset_amount,
                expiry=expiry,
                peer_pubkey=peer_pubkey
            )
            
            log_debug(WALLET, f"Asset invoice created successfully")
            return result

    async def pay_asset_invoice(
        self,
        invoice: str,
        fee_limit_sats: Optional[int] = None,
        peer_pubkey: Optional[str] = None,
        **kwargs,
    ) -> BasePaymentResponse:
        """
        Pay a Taproot Asset invoice.

        Args:
            invoice: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            peer_pubkey: Optional peer public key to specify which channel to use
            **kwargs: Additional parameters including:
                - asset_id: Optional ID of the Taproot Asset to use for payment

        Returns:
            PaymentResponse: Contains information about the payment
        """
        try:
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            
            # Extract asset_id from kwargs if provided
            asset_id = kwargs.get("asset_id")
            asset_info = f" using asset {asset_id[:8]}..." if asset_id else ""
            peer_info = f" with peer {peer_pubkey[:8]}..." if peer_pubkey else ""
            
            log_info(WALLET, f"Paying asset invoice{asset_info}{peer_info}, fee_limit={fee_limit_sats or 'default'} sats")

            # Call the node's pay_asset_invoice method
            payment_result = await self.node.pay_asset_invoice(
                payment_request=invoice,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id,
                peer_pubkey=peer_pubkey
            )

            # Extract payment details
            payment_hash = payment_result.get("payment_hash", "")
            preimage = payment_result.get("payment_preimage", "")
            fee_msat = payment_result.get("fee_sats", 0) * 1000  # Convert sats to msats
            
            log_info(WALLET, f"Payment successful, hash={payment_hash[:8]}..., fee={fee_msat//1000} sats")
            
            # REMOVED: No longer record payment here - this will be handled by the PaymentService
            # This fixes the duplicate payment record issue
            
            # Create a custom response with the asset_id and asset_amount
            response = BasePaymentResponse(
                ok=True,
                checking_id=payment_hash,
                fee_msat=fee_msat,
                preimage=preimage,
                error_message=None
            )
            
            # Store the asset_id in the node's preimage cache
            # This is a workaround since BasePaymentResponse doesn't have an extra field
            asset_id = payment_result.get("asset_id", asset_id)
            if asset_id:
                self.node._store_asset_id(payment_hash, asset_id)
            
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
            await self.cleanup()

    async def update_taproot_assets_after_payment(
        self,
        invoice: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None,
    ) -> BasePaymentResponse:
        """
        Update Taproot Assets after payment has been made from LNbits wallet.
        
        This function is called after a successful payment through the LNbits wallet system
        to update the Taproot Assets daemon about the payment. It is used for internal payments 
        (including self-payments) to update the asset state without requiring an actual 
        Lightning Network payment.

        Args:
            invoice: The payment request (BOLT11 invoice)
            payment_hash: The payment hash of the completed payment
            fee_limit_sats: Optional fee limit in satoshis
            asset_id: Optional asset ID to use for the update

        Returns:
            PaymentResponse: Contains confirmation of the asset update
        """
        try:
            await self.ensure_initialized()
            if self.node is None:
                raise ValueError("Node not initialized")
            log_info(WALLET, f"Processing internal payment for {payment_hash[:8]}..., asset_id={asset_id[:8] if asset_id else 'unknown'}")

            # Get the invoice to retrieve information
            db_invoice = await get_invoice_by_payment_hash(payment_hash)
            if not db_invoice:
                log_error(WALLET, f"Invoice not found for payment hash: {payment_hash}")
                return BasePaymentResponse(
                    ok=False,
                    checking_id=payment_hash,
                    fee_msat=None,
                    preimage=None,
                    error_message="Invoice not found"
                )
            
            # Determine if this is a self-payment
            is_self = await is_self_payment(payment_hash, self.user) if self.user else False
            
            # Use SettlementService to settle the invoice
            success, settlement_result = await SettlementService.settle_invoice(
                payment_hash=payment_hash,
                node=self.node,
                is_internal=True,
                is_self_payment=is_self,
                user_id=self.user,
                wallet_id=self.id
            )
            
            if not success:
                log_error(WALLET, f"Failed to settle internal payment: {settlement_result.get('error', 'Unknown error')}")
                return BasePaymentResponse(
                    ok=False,
                    checking_id=payment_hash,
                    fee_msat=None,
                    preimage=None,
                    error_message=f"Failed to settle internal payment: {settlement_result.get('error', 'Unknown error')}"
                )
            
            # Get preimage from settlement result
            preimage = settlement_result.get('preimage', '')
            
            # Record the payment is now handled by the PaymentService, so we don't need to do it here
            # This avoids duplicating payment records
            
            # Create response
            return BasePaymentResponse(
                ok=True,
                checking_id=payment_hash,
                fee_msat=0,  # No fee for internal payments
                preimage=preimage,
                error_message=None
            )
        except Exception as e:
            log_error(WALLET, f"Failed to update Taproot Assets after payment: {str(e)}")
            return BasePaymentResponse(
                ok=False,
                checking_id=payment_hash,
                fee_msat=None,
                preimage=None,
                error_message=f"Failed to update Taproot Assets: {str(e)}"
            )
        finally:
            await self.cleanup()
