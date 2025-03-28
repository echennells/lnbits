from typing import AsyncGenerator, Dict, List, Optional, Any

from loguru import logger

from lnbits.settings import settings

from .taproot_node import TaprootAssetsNodeExtension
from ..crud import get_or_create_settings
from ..tapd_settings import taproot_settings


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
        self.node = None
        self.initialized = False

    async def _init_connection(self):
        """Initialize the connection to tapd."""
        if self.initialized:
            logger.debug("Connection already initialized, reusing existing node")
            return

        # Create a node instance
        logger.debug("Creating TaprootAssetsNodeExtension instance")
        self.node = TaprootAssetsNodeExtension()

        # Mark as initialized
        self.initialized = True

    async def cleanup(self):
        """Close any open connections."""
        # In the core implementation, this method doesn't actually close the connections
        # We'll keep the connections open to match the core implementation
        pass

    async def list_assets(self) -> List[Dict[str, Any]]:
        """List all Taproot Assets."""
        try:
            await self._init_connection()
            return await self.node.list_assets()
        except Exception as e:
            raise Exception(f"Failed to list assets: {str(e)}")
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
                - peer_pubkey: Optional peer public key to specify which channel to use

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
            # Get channel assets to check if we have multiple channels for this asset
            channel_assets = await self.node.list_channel_assets()
            asset_channels = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
            channel_count = len(asset_channels)
            
            logger.info(f"Found {channel_count} channels for asset_id={asset_id}")
            for idx, channel in enumerate(asset_channels):
                logger.info(f"Channel {idx+1}: channel_point={channel.get('channel_point')}, local_balance={channel.get('local_balance')}")

            # Create the invoice
            peer_pubkey = kwargs.get("peer_pubkey")
            invoice_result = await self.create_asset_invoice(
                memo=memo or "Taproot Asset Transfer",
                asset_id=asset_id,
                asset_amount=amount,
                peer_pubkey=peer_pubkey
            )

            # Extract payment details
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]

            # Create extra data
            extra = {
                "type": "taproot_asset",
                "asset_id": asset_id,
                "asset_amount": amount,
                "channel_count": channel_count,
                "buy_quote": invoice_result.get("accepted_buy_quote", {})
            }

            return InvoiceResponse(
                ok=True,
                payment_hash=payment_hash,
                payment_request=payment_request,
                extra=extra
            )
        except Exception as e:
            logger.error(f"Failed to create invoice: {str(e)}", exc_info=True)
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
        try:
            await self._init_connection()
            return await self.node.create_asset_invoice(
                memo=memo,
                asset_id=asset_id,
                asset_amount=asset_amount,
                expiry=expiry,
                peer_pubkey=peer_pubkey
            )
        except Exception as e:
            logger.error(f"Failed to create asset invoice: {str(e)}", exc_info=True)
            raise Exception(f"Failed to create asset invoice: {str(e)}")
        finally:
            await self.cleanup()

    async def pay_asset_invoice(
        self,
        invoice: str,
        fee_limit_sats: Optional[int] = None,
        peer_pubkey: Optional[str] = None,
        **kwargs,
    ) -> PaymentResponse:
        """
        Pay a Taproot Asset invoice.
        
        WARNING: This method is now deprecated for direct use.
        Use update_taproot_assets_after_payment instead after making the payment with LNbits wallet.

        Args:
            invoice: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            peer_pubkey: Optional peer public key to specify which channel to use
            **kwargs: Additional parameters including:
                - asset_id: Optional ID of the Taproot Asset to use for payment

        Returns:
            PaymentResponse: Contains information about the payment
        """
        logger.warning("pay_asset_invoice is deprecated - payments should be made through LNbits wallet system")
        try:
            await self._init_connection()

            # Extract asset_id from kwargs if provided
            asset_id = kwargs.get("asset_id")
            
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

            return PaymentResponse(
                ok=True,
                checking_id=payment_hash,
                fee_msat=fee_msat,
                preimage=preimage
            )
        except Exception as e:
            logger.error(f"Failed to pay invoice: {str(e)}", exc_info=True)
            return PaymentResponse(
                ok=False,
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
    ) -> PaymentResponse:
        """
        Update Taproot Assets after payment has been made from LNbits wallet.
        
        This function is called after a successful payment through the LNbits wallet system
        to update the Taproot Assets daemon about the payment.

        Args:
            invoice: The payment request (BOLT11 invoice)
            payment_hash: The payment hash of the completed payment
            fee_limit_sats: Optional fee limit in satoshis
            asset_id: Optional asset ID to use for the update

        Returns:
            PaymentResponse: Contains confirmation of the asset update
        """
        try:
            await self._init_connection()
            
            # Call the node's update_after_payment method
            update_result = await self.node.update_after_payment(
                payment_request=invoice,
                payment_hash=payment_hash,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id
            )
            
            return PaymentResponse(
                ok=True,
                checking_id=payment_hash,
                fee_msat=0,  # No additional fee as it was already paid via LNbits
                preimage=update_result.get("preimage", "")
            )
        except Exception as e:
            logger.error(f"Failed to update Taproot Assets after payment: {str(e)}", exc_info=True)
            return PaymentResponse(
                ok=False,
                checking_id=payment_hash,
                error_message=f"Failed to update Taproot Assets: {str(e)}"
            )
        finally:
            await self.cleanup()
