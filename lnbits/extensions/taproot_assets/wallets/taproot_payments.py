import hashlib
from typing import Optional, Dict, Any
import grpc
import grpc.aio
from loguru import logger
from lnbits import bolt11
import re

from .taproot_adapter import (
    taprootassets_pb2,
    tapchannel_pb2,
    lightning_pb2,
    router_pb2
)

class TaprootPaymentManager:
    """
    Handles Taproot Asset payment processing.
    This class is responsible for paying invoices and updating Taproot Assets after payments.
    """

    def __init__(self, node):
        """
        Initialize the payment manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node

    async def pay_asset_invoice(
        self,
        payment_request: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pay a Taproot Asset invoice.

        Args:
            payment_request: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            asset_id: Optional asset ID to use for payment
            peer_pubkey: Optional peer public key to specify which channel to use

        Returns:
            Dict with payment details
        """
        try:
            logger.debug(f"Paying asset invoice: {payment_request[:30]}...")

            # Use default fee limit if not provided
            if fee_limit_sats is None:
                fee_limit_sats = 1000  # Default to 1000 sats fee limit

            # Get payment hash and try to extract asset ID from the invoice
            payment_hash = ""
            try:
                logger.info("=== PAYMENT INVOICE DECODING CHECKPOINT ===")
                decoded = bolt11.decode(payment_request)
                payment_hash = decoded.payment_hash
                logger.info(f"Decoded invoice details:")
                logger.info(f"  - payment_hash: {payment_hash}")
                logger.info(f"  - amount_msat: {decoded.amount_msat}")
                logger.info(f"  - description: {decoded.description}")
                logger.info(f"  - payee: {decoded.payee}")
                logger.info(f"  - date: {decoded.date}")
                logger.info(f"  - expiry: {decoded.expiry}")

                # Log route hints if present
                if hasattr(decoded, 'route_hints') and decoded.route_hints:
                    logger.info("Route hints found in invoice:")
                    for i, hint in enumerate(decoded.route_hints):
                        logger.info(f"Route hint {i+1}:")
                        logger.info(f"  - node_id: {hint.node_id if hasattr(hint, 'node_id') else 'N/A'}")
                        logger.info(f"  - channel_id: {hint.channel_id if hasattr(hint, 'channel_id') else 'N/A'}")
                else:
                    logger.info("No route hints found in invoice")

                # Log all tags for debugging
                logger.info("All invoice tags:")
                for tag in decoded.tags:
                    logger.info(f"  - {tag[0]}: {tag[1]}")

                # Try to extract asset ID from invoice metadata if not provided
                if not asset_id and decoded.tags:
                    for tag in decoded.tags:
                        if tag[0] == 'd' and 'asset_id=' in tag[1]:
                            asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', tag[1])
                            if asset_id_match:
                                asset_id = asset_id_match.group(1)
                                logger.info(f"Successfully extracted asset_id from invoice: {asset_id}")
                                break
                    if not asset_id:
                        logger.info("No asset_id found in invoice tags")
            except Exception as e:
                logger.error(f"Failed to decode invoice: {str(e)}")
                logger.error(f"Full invoice for debugging: {payment_request}")

            # If asset_id is still not available, try to get it from available assets
            if not asset_id:
                try:
                    logger.debug("Asset ID not found in invoice, checking available assets")
                    assets = await self.node.asset_manager.list_assets()
                    if assets and len(assets) > 0:
                        asset_id = assets[0]["asset_id"]
                        logger.debug(f"Using first available asset: {asset_id}")
                    else:
                        raise Exception("No asset ID provided and no assets available")
                except Exception as e:
                    logger.error(f"Failed to get assets: {e}")
                    raise Exception("No asset ID provided and failed to get available assets")

            logger.debug(f"Using asset_id: {asset_id}")

            # Convert asset_id to bytes
            asset_id_bytes = bytes.fromhex(asset_id)
            logger.info(f"Using asset_id_bytes: {asset_id_bytes.hex()}")

            # Try to pay the invoice with Lightning directly first
            try:
                logger.info("=== PAYMENT REQUEST CREATION CHECKPOINT ===")
                # Log the original payment request for debugging
                logger.info(f"Original payment request: {payment_request}")

                # Create the router payment request
                router_payment_request = router_pb2.SendPaymentRequest(
                    payment_request=payment_request,
                    fee_limit_sat=fee_limit_sats,
                    timeout_seconds=60,  # 1 minute timeout
                    no_inflight_updates=False
                )
                logger.info(f"Created router payment request with fee_limit_sat={fee_limit_sats}")

                # Log available channels for this asset
                logger.info("=== AVAILABLE CHANNELS CHECKPOINT ===")
                channel_assets = await self.node.asset_manager.list_channel_assets()
                asset_channels = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
                logger.info(f"Found {len(asset_channels)} channels for asset_id={asset_id}")
                for idx, channel in enumerate(asset_channels):
                    logger.info(f"Channel {idx+1}:")
                    logger.info(f"  - channel_id: {channel.get('channel_id')}")
                    logger.info(f"  - channel_id (hex): {hex(int(channel.get('channel_id')))}")
                    logger.info(f"  - remote_pubkey: {channel.get('remote_pubkey')}")
                    logger.info(f"  - local_balance: {channel.get('local_balance')}")

                logger.info("=== SEND PAYMENT REQUEST CREATION CHECKPOINT ===")
                # Create the SendPayment request
                request = tapchannel_pb2.SendPaymentRequest(
                    payment_request=router_payment_request,
                    asset_id=asset_id_bytes,  # Include the asset ID
                    allow_overpay=True  # Allow payment even if it's uneconomical
                )
                logger.info(f"Created SendPayment request:")
                logger.info(f"  - asset_id: {asset_id}")
                logger.info(f"  - allow_overpay: True")

                # Log the decoded invoice route hints for comparison
                logger.info("=== INVOICE ROUTE HINTS CHECKPOINT ===")
                decoded = bolt11.decode(payment_request)
                if hasattr(decoded, 'route_hints') and decoded.route_hints:
                    for i, hint in enumerate(decoded.route_hints):
                        logger.info(f"Invoice route hint {i+1}:")
                        if hasattr(hint, 'node_id'):
                            logger.info(f"  - node_id: {hint.node_id}")
                        if hasattr(hint, 'channel_id'):
                            logger.info(f"  - channel_id: {hint.channel_id}")
                            logger.info(f"  - channel_id (hex): {hex(hint.channel_id) if isinstance(hint.channel_id, int) else 'N/A'}")
                else:
                    logger.info("No route hints found in decoded invoice")

                # Add peer_pubkey if provided
                if peer_pubkey:
                    logger.info(f"Adding peer_pubkey to request: {peer_pubkey}")
                    request.peer_pubkey = bytes.fromhex(peer_pubkey)
                    logger.info(f"Peer pubkey bytes: {request.peer_pubkey.hex()}")
                else:
                    logger.info("No peer_pubkey provided")

                logger.info(f"Calling tapchannel_stub.SendPayment with asset_id={asset_id}")

                logger.info("=== PAYMENT STREAM PROCESSING CHECKPOINT ===")
                # Get the stream object
                response_stream = self.node.tapchannel_stub.SendPayment(request)

                # Process the stream responses
                payment_status = "pending"
                preimage = ""
                fee_sat = 0

                try:
                    async for response in response_stream:
                        logger.info(f"Got payment response type: {type(response)}")
                        logger.info(f"Payment response fields: {[field.name for field in response.DESCRIPTOR.fields]}")
                        logger.info(f"Full response: {response}")

                        if hasattr(response, 'accepted_sell_order') and response.HasField('accepted_sell_order'):
                            logger.debug("Received accepted sell order response")
                            continue

                        elif hasattr(response, 'payment_result') and response.HasField('payment_result'):
                            payment_result = response.payment_result

                            if payment_result.status == 1:  # SUCCEEDED
                                payment_status = "success"

                                if hasattr(payment_result, 'payment_preimage'):
                                    preimage = payment_result.payment_preimage.hex() if isinstance(payment_result.payment_preimage, bytes) else str(payment_result.payment_preimage)

                                if hasattr(payment_result, 'fee_msat'):
                                    fee_sat = payment_result.fee_msat // 1000

                                logger.debug(f"Payment succeeded: hash={payment_hash}, preimage={preimage}, fee={fee_sat} sat")
                                break

                            elif payment_result.status == 3:  # FAILED
                                payment_status = "failed"
                                failure_reason = payment_result.failure_reason if hasattr(payment_result, 'failure_reason') else "Unknown failure"
                                logger.error(f"Payment failed: {failure_reason}")
                                raise Exception(f"Payment failed: {failure_reason}")

                    if payment_status != "success":
                        raise Exception("Payment did not succeed or timed out")

                except grpc.aio.AioRpcError as e:
                    logger.error(f"gRPC error in payment stream: {e.code()}: {e.details()}")
                    raise Exception(f"gRPC error: {e.code()}: {e.details()}")

                except Exception as e:
                    logger.error(f"Error processing payment stream: {e}")
                    raise

                # Return successful response
                return {
                    "payment_hash": payment_hash,
                    "payment_preimage": preimage,
                    "fee_sats": fee_sat,
                    "status": "success",
                    "payment_request": payment_request
                }

            except Exception as e:
                logger.error(f"Failed to pay using Taproot channel: {e}")

                # Fall back to standard Lightning payment
                try:
                    logger.debug("Falling back to standard Lightning payment")

                    # Create payment request with fee limit
                    fee_limit_obj = lightning_pb2.FeeLimit(fixed=fee_limit_sats * 1000)  # Convert to millisatoshis

                    request = lightning_pb2.SendRequest(
                        payment_request=payment_request,
                        fee_limit=fee_limit_obj,
                        allow_self_payment=True
                    )

                    # Make the SendPaymentSync call
                    response = await self.node.ln_stub.SendPaymentSync(request)

                    if hasattr(response, 'payment_error') and response.payment_error:
                        logger.error(f"Payment failed: {response.payment_error}")
                        raise Exception(f"Payment failed: {response.payment_error}")

                    # Extract payment details
                    preimage = response.payment_preimage.hex() if hasattr(response, 'payment_preimage') else ""
                    fee_sat = response.payment_route.total_fees_msat // 1000 if hasattr(response, 'payment_route') else 0

                    # Return successful response
                    return {
                        "payment_hash": payment_hash,
                        "payment_preimage": preimage,
                        "fee_sats": fee_sat,
                        "status": "success",
                        "payment_request": payment_request
                    }

                except Exception as fallback_error:
                    logger.error(f"Fallback Lightning payment also failed: {fallback_error}")
                    raise Exception(f"All payment methods failed. Last error: {str(fallback_error)}")

        except Exception as e:
            logger.error(f"Payment failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to pay asset invoice: {str(e)}")

    async def update_after_payment(
        self,
        payment_request: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update Taproot Assets after a payment has been made through the LNbits wallet.

        This method notifies the Taproot Asset daemon that a payment has been completed
        so it can update its internal state, but doesn't actually send any Bitcoin payment
        since that was already handled by the LNbits wallet system.

        Args:
            payment_request: The original BOLT11 invoice
            payment_hash: The payment hash of the completed payment
            fee_limit_sats: Optional fee limit in satoshis (not used for actual payment now)
            asset_id: Optional asset ID to use for the update

        Returns:
            Dict containing the update confirmation
        """
        try:
            # Try to extract asset_id from the payment_request if not provided
            if not asset_id:
                try:
                    decoded = bolt11.decode(payment_request)
                    if decoded.tags:
                        for tag in decoded.tags:
                            if tag[0] == 'd' and 'asset_id=' in tag[1]:
                                asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', tag[1])
                                if asset_id_match:
                                    asset_id = asset_id_match.group(1)
                                    logger.debug(f"Extracted asset_id from invoice: {asset_id}")
                                    break
                except Exception as e:
                    logger.warning(f"Failed to extract asset ID from invoice: {e}")

            # If asset_id is still not available, try to get it from available assets
            if not asset_id:
                try:
                    logger.debug("Asset ID not found in invoice, checking available assets")
                    assets = await self.node.asset_manager.list_assets()
                    if assets and len(assets) > 0:
                        asset_id = assets[0]["asset_id"]
                        logger.debug(f"Using first available asset: {asset_id}")
                    else:
                        raise Exception("No asset ID provided and no assets available")
                except Exception as e:
                    logger.error(f"Failed to get assets: {e}")
                    raise Exception("No asset ID provided and failed to get available assets")

            logger.info(f"=== SETTLEMENT PROCESS STARTING ===")
            logger.info(f"Payment hash: {payment_hash}")
            logger.info(f"Asset ID: {asset_id}")

            # Convert asset_id to bytes
            asset_id_bytes = bytes.fromhex(asset_id)

            # First settle the HODL invoice using the stored preimage
            try:
                # Retrieve the preimage for this payment hash
                logger.info(f"Looking up preimage for payment hash: {payment_hash}")
                logger.info(f"Current preimage cache size: {len(self.node._preimage_cache)}")
                preimage_hex = self.node._get_preimage(payment_hash)

                if not preimage_hex:
                    # If not found, log an error
                    logger.error(f"No preimage found for payment hash: {payment_hash}")
                    logger.error(f"Available payment hashes in cache: {list(self.node._preimage_cache.keys())}")
                    raise Exception(f"Cannot settle HODL invoice: no preimage found for {payment_hash}")

                logger.info(f"Found preimage: {preimage_hex}")
                logger.info("Converting preimage to bytes and creating settlement request")

                preimage_bytes = bytes.fromhex(preimage_hex)
                logger.info(f"Preimage bytes length: {len(preimage_bytes)}")

                settle_request = invoices_pb2.SettleInvoiceMsg(
                    preimage=preimage_bytes
                )

                logger.info("Calling SettleInvoice RPC...")
                await self.node.invoices_stub.SettleInvoice(settle_request, timeout=30)
                logger.info("Successfully settled HODL invoice")
            except Exception as e:
                logger.error(f"Failed to settle HODL invoice: {e}")
                raise Exception(f"Failed to settle HODL invoice: {str(e)}")

            # Then notify the Taproot daemon about the payment status
            try:
                logger.info("=== NOTIFYING TAPROOT DAEMON ===")
                logger.info("Creating payment notification request")

                payment_hash_bytes = bytes.fromhex(payment_hash)
                logger.info(f"Payment hash bytes length: {len(payment_hash_bytes)}")

                request = tapchannel_pb2.PaymentNotificationRequest(
                    payment_hash=payment_hash_bytes,
                    asset_id=asset_id_bytes,
                    status="SUCCEEDED"
                )

                logger.info("Calling NotifyPaymentStatus RPC...")
                await self.node.tapchannel_stub.NotifyPaymentStatus(request, timeout=30)
                logger.info("Successfully notified Taproot daemon")
            except Exception as e:
                logger.error(f"Failed to notify Taproot daemon: {e}")
                raise Exception(f"Failed to notify Taproot daemon: {str(e)}")

            logger.info("=== SETTLEMENT COMPLETED ===")
            result = {
                "success": True,
                "payment_hash": payment_hash,
                "message": "HODL invoice settled and Taproot Assets updated successfully",
                "preimage": preimage_hex  # Return the actual preimage instead of payment hash
            }

            logger.debug(f"Update completed successfully: {result}")
            return result

        except Exception as e:
            logger.error(f"Failed to update Taproot Assets after payment: {str(e)}", exc_info=True)
            raise Exception(f"Failed to update Taproot Assets: {str(e)}")
