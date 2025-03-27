# Full file: /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/wallets/taproot_wallet.py
import asyncio
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

        # DEBUG: Log the start of invoice creation
        logger.info(f"DEBUG: TaprootWalletExtension.create_invoice starting with asset_id={asset_id}, amount={amount}")

        try:
            # Get channel assets to check if we have multiple channels for this asset
            try:
                logger.info(f"DEBUG: Checking channel count for asset_id={asset_id}")
                channel_assets = await self.node.list_channel_assets()
                asset_channels = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
                channel_count = len(asset_channels)
                
                logger.info(f"DEBUG: Found {channel_count} channels for asset_id={asset_id}")
                for idx, channel in enumerate(asset_channels):
                    logger.info(f"DEBUG: Channel {idx+1}: channel_point={channel.get('channel_point')}, local_balance={channel.get('local_balance')}")
            except Exception as e:
                logger.error(f"DEBUG: Error checking channel count: {e}", exc_info=True)
                channel_count = 0  # Default to 0 if we can't determine

            # Create the invoice
            try:
                logger.info(f"DEBUG: Calling create_asset_invoice with asset_id={asset_id}, amount={amount}, channel_count={channel_count}")
                # Extract peer_pubkey from kwargs if provided
                peer_pubkey = kwargs.get("peer_pubkey")
                
                invoice_result = await self.create_asset_invoice(
                    memo=memo or "Taproot Asset Transfer",
                    asset_id=asset_id,
                    asset_amount=amount,
                    peer_pubkey=peer_pubkey
                )
                logger.info(f"DEBUG: Got invoice_result, type: {type(invoice_result)}")

                # AGGRESSIVE DEBUGGING: Dump the entire invoice_result
                logger.info(f"DEBUG: Full invoice_result: {invoice_result}")

                # Check if invoice_result is a dictionary or something else
                if not isinstance(invoice_result, dict):
                    logger.info(f"DEBUG: invoice_result is not a dict! Converting from {type(invoice_result)}")
                    invoice_result = {"invoice_result": {"r_hash": "", "payment_request": ""}, "accepted_buy_quote": {}}

                # Check each key in the invoice_result
                for key in invoice_result:
                    logger.info(f"DEBUG: Key {key} has type {type(invoice_result[key])}")

                    # If the key is accepted_buy_quote, ensure it's a dictionary
                    if key == "accepted_buy_quote":
                        logger.info(f"DEBUG: Examining accepted_buy_quote: {invoice_result[key]}")
                        
                        # Check if created_time exists in accepted_buy_quote
                        if isinstance(invoice_result[key], dict) and "created_time" in invoice_result[key]:
                            logger.info(f"DEBUG: accepted_buy_quote has created_time: {invoice_result[key]['created_time']}")
                        else:
                            logger.info("DEBUG: accepted_buy_quote does NOT have created_time field")
                        
                        if not isinstance(invoice_result[key], dict):
                            logger.info(f"DEBUG: accepted_buy_quote is not a dict! Converting from {type(invoice_result[key])}")
                            if isinstance(invoice_result[key], (list, tuple)):
                                invoice_result[key] = {"items": list(invoice_result[key])}
                            else:
                                invoice_result[key] = {"value": str(invoice_result[key])}
                            logger.info(f"DEBUG: Converted accepted_buy_quote: {invoice_result[key]}")

            except Exception as e:
                logger.error(f"DEBUG: Error in create_asset_invoice: {e}", exc_info=True)
                raise

            # Extract the payment hash and payment request with explicit error handling
            logger.info("DEBUG: Extracting payment_hash and payment_request")
            try:
                payment_hash = invoice_result["invoice_result"]["r_hash"]
                logger.info(f"DEBUG: Extracted payment_hash: {payment_hash}")
            except (KeyError, TypeError) as e:
                logger.error(f"DEBUG: Failed to extract payment_hash: {e}", exc_info=True)
                payment_hash = ""

            try:
                payment_request = invoice_result["invoice_result"]["payment_request"]
                logger.info(f"DEBUG: Extracted payment_request: {payment_request[:30]}...")
            except (KeyError, TypeError) as e:
                logger.error(f"DEBUG: Failed to extract payment_request: {e}", exc_info=True)
                payment_request = ""

            # Create extra data with guaranteed dictionary format
            logger.info("DEBUG: Creating extra data")
            extra = {
                "type": "taproot_asset",
                "asset_id": asset_id,
                "asset_amount": amount,
                "channel_count": channel_count,  # Add channel count to extra data
                "buy_quote": {}  # Initialize with empty dict
            }

            # Only add buy_quote if it exists, is not empty, and can be safely converted
            if "accepted_buy_quote" in invoice_result and invoice_result["accepted_buy_quote"]:
                logger.info(f"DEBUG: Processing accepted_buy_quote of type {type(invoice_result['accepted_buy_quote'])}")

                try:
                    # Get the buy_quote and ensure it's a dictionary
                    buy_quote = invoice_result["accepted_buy_quote"]

                    # Check if created_time exists in buy_quote
                    if isinstance(buy_quote, dict) and "created_time" in buy_quote:
                        logger.info(f"DEBUG: buy_quote has created_time: {buy_quote['created_time']}")
                    else:
                        logger.info("DEBUG: buy_quote does NOT have created_time field")

                    # Force conversion to dictionary regardless of type
                    if not isinstance(buy_quote, dict):
                        logger.info(f"DEBUG: Converting buy_quote from {type(buy_quote)} to dict")
                        if isinstance(buy_quote, (list, tuple)):
                            buy_quote = {"items": list(buy_quote)}
                        else:
                            buy_quote = {"value": str(buy_quote)}

                    # Set the buy_quote in the extra data
                    extra["buy_quote"] = buy_quote
                    logger.info(f"DEBUG: Final buy_quote in extra: {extra['buy_quote']}")
                except Exception as e:
                    logger.error(f"DEBUG: Error processing buy_quote: {e}", exc_info=True)
                    # Keep the default empty dict for buy_quote

            logger.info(f"DEBUG: Final extra data: {extra}")

            # Return the invoice response with guaranteed structure
            logger.info("DEBUG: Returning successful InvoiceResponse")
            return InvoiceResponse(
                ok=True,
                payment_hash=payment_hash,
                payment_request=payment_request,
                extra=extra
            )
        except Exception as e:
            logger.error(f"DEBUG: Failed to create invoice: {str(e)}", exc_info=True)
            # Log the full exception traceback
            import traceback
            logger.error(f"DEBUG: Full exception traceback: {traceback.format_exc()}")
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

        Returns:
            Dict containing the invoice information with accepted_buy_quote and invoice_result
        """
        try:
            await self._init_connection()

            # DEBUG: Log the start of asset invoice creation
            logger.info(f"DEBUG: TaprootWalletExtension.create_asset_invoice starting with asset_id={asset_id}, amount={asset_amount}")

            # Get channel assets to check if we have multiple channels for this asset
            try:
                logger.info(f"DEBUG: Checking channel count for asset_id={asset_id}")
                channel_assets = await self.node.list_channel_assets()
                asset_channels = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
                channel_count = len(asset_channels)
                
                logger.info(f"DEBUG: Found {channel_count} channels for asset_id={asset_id}")
                for idx, channel in enumerate(asset_channels):
                    logger.info(f"DEBUG: Channel {idx+1}: channel_point={channel.get('channel_point')}, local_balance={channel.get('local_balance')}")
            except Exception as e:
                logger.error(f"DEBUG: Error checking channel count: {e}", exc_info=True)
                channel_count = 0  # Default to 0 if we can't determine

            # Use the node instance to create the invoice
            logger.info(f"DEBUG: Calling node.create_asset_invoice with asset_id={asset_id}, amount={asset_amount}")
            response = await self.node.create_asset_invoice(
                memo=memo,
                asset_id=asset_id,
                asset_amount=asset_amount,
                peer_pubkey=peer_pubkey
            )

            # Debug the response
            logger.info(f"DEBUG: Response from node.create_asset_invoice: {response}")
            logger.info(f"DEBUG: Response type: {type(response)}")

            # Check if created_time exists in the response
            if isinstance(response, dict):
                if "created_time" in response:
                    logger.info(f"DEBUG: Response has created_time at top level: {response['created_time']}")
                else:
                    logger.info("DEBUG: Response does NOT have created_time at top level")
                
                if "accepted_buy_quote" in response and isinstance(response["accepted_buy_quote"], dict):
                    if "created_time" in response["accepted_buy_quote"]:
                        logger.info(f"DEBUG: accepted_buy_quote has created_time: {response['accepted_buy_quote']['created_time']}")
                    else:
                        logger.info("DEBUG: accepted_buy_quote does NOT have created_time")

            # Ensure response is a dictionary
            if not isinstance(response, dict):
                logger.warning(f"DEBUG: Response is not a dictionary, converting from {type(response)}")
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
                logger.warning(f"DEBUG: accepted_buy_quote is not a dictionary, converting from {type(response['accepted_buy_quote'])}")
                if isinstance(response["accepted_buy_quote"], (list, tuple)):
                    response["accepted_buy_quote"] = {"items": list(response["accepted_buy_quote"])}
                else:
                    response["accepted_buy_quote"] = {"value": str(response["accepted_buy_quote"])}

            # Add channel_count to the response for debugging
            if isinstance(response, dict):
                response["debug_channel_count"] = channel_count

            logger.info(f"DEBUG: Final response from create_asset_invoice: {response}")
            return response
        except Exception as e:
            logger.error(f"DEBUG: Failed to create asset invoice: {str(e)}", exc_info=True)
            # Log the full exception traceback
            import traceback
            logger.error(f"DEBUG: Full exception traceback: {traceback.format_exc()}")
            raise Exception(f"Failed to create asset invoice: {str(e)}")
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
            
            logger.debug(f"Notifying Taproot Assets daemon about payment: {payment_hash}")
            
            # Call the node's update_after_payment method
            update_result = await self.node.update_after_payment(
                payment_request=invoice,
                payment_hash=payment_hash,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id
            )
            
            logger.debug(f"Update result: {update_result}")
            
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

            logger.debug(f"Sending payment for invoice: {invoice[:30]}...")

            # Extract asset_id from kwargs if provided
            asset_id = kwargs.get("asset_id")
            
            # Log if peer_pubkey is provided
            if peer_pubkey:
                logger.debug(f"Using peer_pubkey for payment: {peer_pubkey}")

            # Call the node's pay_asset_invoice method
            payment_result = await self.node.pay_asset_invoice(
                payment_request=invoice,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id,
                peer_pubkey=peer_pubkey  # Pass peer_pubkey to the node
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
