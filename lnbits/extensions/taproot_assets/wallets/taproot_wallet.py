# Full file: /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/wallets/taproot_wallet.py
import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Any

from loguru import logger

from lnbits.settings import settings

from .taproot_node import TaprootAssetsNodeExtension
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


# Helper function to convert protobuf message to a JSON-serializable dict
def protobuf_to_dict(pb_obj):
    """Convert a protobuf object to a JSON-serializable dict."""
    if pb_obj is None:
        return None

    result = {}

    # Get all fields from the protobuf object
    for field_name in pb_obj.DESCRIPTOR.fields_by_name:
        value = getattr(pb_obj, field_name)

        # Handle different types of values
        if isinstance(value, bytes):
            # Convert bytes to hex string
            result[field_name] = value.hex()
        elif hasattr(value, 'DESCRIPTOR'):
            # Recursively convert nested protobuf objects
            result[field_name] = protobuf_to_dict(value)
        elif isinstance(value, (list, tuple)):
            # Handle repeated fields
            result[field_name] = [
                protobuf_to_dict(item) if hasattr(item, 'DESCRIPTOR') else item
                for item in value
            ]
        else:
            # Primitive types (int, float, bool, str)
            result[field_name] = value

    return result


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
                logger.debug(f"TRACE 1: Calling create_asset_invoice with asset_id={asset_id}, amount={amount}")
                invoice_result = await self.create_asset_invoice(
                    memo=memo or "Taproot Asset Transfer",
                    asset_id=asset_id,
                    asset_amount=amount
                )
                logger.debug(f"TRACE 2: Got invoice_result, type: {type(invoice_result)}")

                # AGGRESSIVE DEBUGGING: Dump the entire invoice_result
                logger.debug(f"TRACE 3: Full invoice_result: {invoice_result}")

                # Check if invoice_result is a dictionary or something else
                if not isinstance(invoice_result, dict):
                    logger.debug(f"TRACE 4: invoice_result is not a dict! Converting from {type(invoice_result)}")
                    invoice_result = {"invoice_result": {"r_hash": "", "payment_request": ""}, "accepted_buy_quote": {}}

                # Check each key in the invoice_result
                for key in invoice_result:
                    logger.debug(f"TRACE 5: Key {key} has type {type(invoice_result[key])}")

                    # If the key is accepted_buy_quote, ensure it's a dictionary
                    if key == "accepted_buy_quote":
                        if not isinstance(invoice_result[key], dict):
                            logger.debug(f"TRACE 6: accepted_buy_quote is not a dict! Converting from {type(invoice_result[key])}")
                            if isinstance(invoice_result[key], (list, tuple)):
                                invoice_result[key] = {"items": list(invoice_result[key])}
                            else:
                                invoice_result[key] = {"value": str(invoice_result[key])}
                            logger.debug(f"TRACE 7: Converted accepted_buy_quote: {invoice_result[key]}")

            except Exception as e:
                logger.warning(f"TRACE ERROR: Error in create_asset_invoice: {e}", exc_info=True)
                raise

            # Extract the payment hash and payment request with explicit error handling
            logger.debug("TRACE 8: Extracting payment_hash and payment_request")
            try:
                payment_hash = invoice_result["invoice_result"]["r_hash"]
                logger.debug(f"TRACE 9: Extracted payment_hash: {payment_hash}")
            except (KeyError, TypeError) as e:
                logger.error(f"TRACE ERROR: Failed to extract payment_hash: {e}", exc_info=True)
                payment_hash = ""

            try:
                payment_request = invoice_result["invoice_result"]["payment_request"]
                logger.debug(f"TRACE 10: Extracted payment_request: {payment_request[:30]}...")
            except (KeyError, TypeError) as e:
                logger.error(f"TRACE ERROR: Failed to extract payment_request: {e}", exc_info=True)
                payment_request = ""

            # Create extra data with guaranteed dictionary format
            logger.debug("TRACE 11: Creating extra data")
            extra = {
                "type": "taproot_asset",
                "asset_id": asset_id,
                "asset_amount": amount,
                "buy_quote": {}  # Initialize with empty dict
            }

            # Only add buy_quote if it exists, is not empty, and can be safely converted
            if "accepted_buy_quote" in invoice_result and invoice_result["accepted_buy_quote"]:
                logger.debug(f"TRACE 12: Processing accepted_buy_quote of type {type(invoice_result['accepted_buy_quote'])}")

                try:
                    # Get the buy_quote and ensure it's a dictionary
                    buy_quote = invoice_result["accepted_buy_quote"]

                    # Force conversion to dictionary regardless of type
                    if not isinstance(buy_quote, dict):
                        logger.debug(f"TRACE 13: Converting buy_quote from {type(buy_quote)} to dict")
                        if isinstance(buy_quote, (list, tuple)):
                            buy_quote = {"items": list(buy_quote)}
                        else:
                            buy_quote = {"value": str(buy_quote)}

                    # Set the buy_quote in the extra data
                    extra["buy_quote"] = buy_quote
                    logger.debug(f"TRACE 14: Final buy_quote in extra: {extra['buy_quote']}")
                except Exception as e:
                    logger.error(f"TRACE ERROR: Error processing buy_quote: {e}", exc_info=True)
                    # Keep the default empty dict for buy_quote

            logger.debug(f"TRACE 15: Final extra data: {extra}")

            # Return the invoice response with guaranteed structure
            return InvoiceResponse(
                ok=True,
                payment_hash=payment_hash,
                payment_request=payment_request,
                extra=extra
            )
        except Exception as e:
            logger.error(f"TRACE ERROR: Failed to create invoice: {str(e)}", exc_info=True)
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

        This uses the TaprootAssetChannels service's AddInvoice method that is specifically
        designed for asset invoices. The RFQ (Request for Quote) process is handled internally
        by the Taproot Assets daemon.

        Args:
            memo: Description for the invoice
            asset_id: The ID of the Taproot Asset
            asset_amount: The amount of the asset to transfer
            expiry: Optional expiry time in seconds

        Returns:
            Dict containing the invoice information with accepted_buy_quote and invoice_result
        """
        try:
            await self._init_connection()

            # Use the node instance to create the invoice
            response = await self.node.create_asset_invoice(
                memo=memo,
                asset_id=asset_id,
                asset_amount=asset_amount
            )

            # Debug the response
            logger.debug(f"Response from node.create_asset_invoice: {response}")
            logger.debug(f"Response type: {type(response)}")

            # Ensure response is a dictionary
            if not isinstance(response, dict):
                logger.warning(f"Response is not a dictionary, converting from {type(response)}")
                # Convert to a dictionary with expected structure if it's not already
                if isinstance(response, (list, tuple)):
                    response = {
                        "accepted_buy_quote": {"items": list(response)},
                        "invoice_result": {"r_hash": "", "payment_request": ""}
                    }
                else:
                    response = {
                        "accepted_buy_quote": {},
                        "invoice_result": {"r_hash": "", "payment_request": ""}
                    }

            # Ensure accepted_buy_quote is a dictionary
            if "accepted_buy_quote" in response and not isinstance(response["accepted_buy_quote"], dict):
                logger.warning(f"accepted_buy_quote is not a dictionary, converting from {type(response['accepted_buy_quote'])}")
                if isinstance(response["accepted_buy_quote"], (list, tuple)):
                    response["accepted_buy_quote"] = {"items": list(response["accepted_buy_quote"])}
                else:
                    response["accepted_buy_quote"] = {"value": str(response["accepted_buy_quote"])}

            return response
        except Exception as e:
            logger.error(f"Failed to create asset invoice: {str(e)}", exc_info=True)
            raise Exception(f"Failed to create asset invoice: {str(e)}")
        finally:
            await self.cleanup()

    async def pay_asset_invoice(
        self,
        invoice: str,
        fee_limit_sats: Optional[int] = None,
        **kwargs,
    ) -> PaymentResponse:
        """
        Pay a Taproot Asset invoice.
        
        Args:
            invoice: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            **kwargs: Additional parameters
            
        Returns:
            PaymentResponse: Contains information about the payment
        """
        try:
            await self._init_connection()
            
            logger.debug(f"Sending payment for invoice: {invoice[:30]}...")
            
            # Call the node's pay_asset_invoice method
            payment_result = await self.node.pay_asset_invoice(
                payment_request=invoice,
                fee_limit_sats=fee_limit_sats
            )
            
            logger.debug(f"Payment result: {payment_result}")
            
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
