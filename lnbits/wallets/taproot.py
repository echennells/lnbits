import asyncio
from typing import AsyncGenerator, Optional

from loguru import logger

from lnbits.nodes.tapd import TaprootAssetsNode
from lnbits.settings import settings

from .base import (
    InvoiceResponse,
    PaymentPendingStatus,
    PaymentResponse,
    PaymentStatus,
    StatusResponse,
    Wallet,
)


class TaprootAssetsWallet(Wallet):
    """
    Wallet implementation for Taproot Assets.
    This wallet interfaces with a Taproot Assets daemon (tapd) to provide
    functionality for managing and transacting with Taproot Assets.
    """

    __node_cls__ = TaprootAssetsNode

    def __init__(self):
        super().__init__()
        
        # Validate required settings
        if not settings.tapd_host:
            raise ValueError("cannot initialize TaprootAssetsWallet: missing tapd_host")
        
        if not settings.tapd_tls_cert_path:
            raise ValueError("cannot initialize TaprootAssetsWallet: missing tapd_tls_cert_path")
        
        if not settings.tapd_macaroon_path and not settings.tapd_macaroon_hex:
            raise ValueError(
                "cannot initialize TaprootAssetsWallet: "
                "missing tapd_macaroon_path or tapd_macaroon_hex"
            )

    async def cleanup(self):
        """Close any open connections."""
        pass

    async def status(self) -> StatusResponse:
        """
        Get the status of the Taproot Assets wallet.
        
        Returns:
            StatusResponse: Contains error message (if any) and balance in msat.
        """
        try:
            # Create a node instance
            node = self.__node_cls__(wallet=self)
            
            # Get assets to check connection
            assets = await node.list_assets()
            await node.close()
            
            # For Taproot Assets, we don't have a direct balance in msat
            # Instead, we return the count of assets as an indicator
            return StatusResponse(None, len(assets) * 1000)
        except Exception as exc:
            logger.warning(f"Error getting Taproot Assets status: {exc}")
            return StatusResponse(f"Unable to connect to tapd: {exc}", 0)

    async def create_invoice(
        self,
        amount: int,
        memo: Optional[str] = None,
        description_hash: Optional[bytes] = None,
        unhashed_description: Optional[bytes] = None,
        **kwargs,
    ) -> InvoiceResponse:
        """
        Create an invoice for a Taproot Asset transfer.
        
        Args:
            amount: Amount of the asset to transfer
            memo: Optional description for the invoice
            description_hash: Optional hash of the description
            unhashed_description: Optional unhashed description
            **kwargs: Additional parameters including:
                - asset_id: ID of the Taproot Asset (required)
        
        Returns:
            InvoiceResponse: Contains payment hash and payment request
        """
        # Extract asset_id from kwargs
        asset_id = kwargs.get("asset_id")
        
        if not asset_id:
            logger.warning("Missing asset_id parameter in create_invoice")
            return InvoiceResponse(False, None, None, "Missing asset_id parameter", None)
        
        try:
            # Create a node instance
            node = self.__node_cls__(wallet=self)
            
            # Create the invoice
            try:
                invoice_result = await node.create_asset_invoice(
                    memo=memo or "Taproot Asset Transfer",
                    asset_id=asset_id,
                    asset_amount=amount
                )
            except Exception as e:
                logger.warning(f"Error in node.create_asset_invoice: {e}")
                raise
            
            await node.close()
            
            # Extract the payment hash and payment request
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]
            
            # Helper function to ensure all values are JSON serializable
            def ensure_serializable(obj):
                """Recursively convert an object to JSON serializable types."""
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
                # Make sure we're not adding an empty dictionary
                if invoice_result["accepted_buy_quote"] and isinstance(invoice_result["accepted_buy_quote"], dict) and len(invoice_result["accepted_buy_quote"]) > 0:
                    # Ensure the buy_quote is fully serializable
                    serializable_buy_quote = ensure_serializable(invoice_result["accepted_buy_quote"])
                    extra["buy_quote"] = serializable_buy_quote
            
            logger.debug(f"Created Taproot Asset invoice: asset_id={asset_id}, amount={amount}")
            
            return InvoiceResponse(True, payment_hash, payment_request, None, extra)
        except Exception as exc:
            logger.warning(f"Error creating Taproot Asset invoice: {exc}")
            return InvoiceResponse(False, None, None, str(exc), None)

    async def pay_invoice(
        self, bolt11: str, fee_limit_msat: int
    ) -> PaymentResponse:
        """
        Pay a Taproot Asset invoice.
        
        Args:
            bolt11: BOLT11 invoice string
            fee_limit_msat: Maximum fee to pay in millisatoshis
            
        Returns:
            PaymentResponse: Contains payment status and details
        """
        # This is a placeholder implementation
        # Taproot Asset payments require additional logic to handle the asset transfer
        return PaymentResponse(
            None, None, None, None, "Taproot Asset payments not yet implemented"
        )

    async def get_invoice_status(
        self, checking_id: str
    ) -> PaymentStatus:
        """
        Check the status of a Taproot Asset invoice.
        
        Args:
            checking_id: Payment hash to check
            
        Returns:
            PaymentStatus: Status of the invoice
        """
        # This is a placeholder implementation
        # Would need to query tapd for the status of the asset transfer
        return PaymentPendingStatus()

    async def get_payment_status(
        self, checking_id: str
    ) -> PaymentStatus:
        """
        Check the status of a Taproot Asset payment.
        
        Args:
            checking_id: Payment hash to check
            
        Returns:
            PaymentStatus: Status of the payment
        """
        # This is a placeholder implementation
        # Would need to query tapd for the status of the asset transfer
        return PaymentPendingStatus()

    async def paid_invoices_stream(self) -> AsyncGenerator[str, None]:
        """
        Stream of paid invoices.
        
        Yields:
            str: Payment hash of paid invoice
        """
        # This is a placeholder implementation
        # Would need to subscribe to tapd events for asset transfers
        while settings.lnbits_running:
            await asyncio.sleep(5)
            # In a real implementation, we would yield payment hashes here
            # For now, we just continue the loop without yielding anything
