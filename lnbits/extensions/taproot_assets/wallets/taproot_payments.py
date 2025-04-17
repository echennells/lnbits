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

            # Set default fee limit with minimum for routing
            fee_limit_sats = max(fee_limit_sats or 1000, 10)
            logger.info(f"Using fee_limit_sats={fee_limit_sats} for payment")

            # Decode invoice to get payment hash and extract asset ID if needed
            try:
                decoded = bolt11.decode(payment_request)
                payment_hash = decoded.payment_hash
                logger.info(f"Payment hash: {payment_hash}")
                
                # Extract asset ID from invoice if not provided
                if not asset_id:
                    for tag in decoded.tags:
                        if tag[0] == 'd' and 'asset_id=' in tag[1]:
                            asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', tag[1])
                            if asset_id_match:
                                asset_id = asset_id_match.group(1)
                                logger.info(f"Extracted asset_id from invoice: {asset_id}")
                                break
            except Exception as e:
                logger.error(f"Failed to decode invoice: {str(e)}")
                raise Exception(f"Invalid invoice format: {str(e)}")

            # Require a valid asset ID
            if not asset_id:
                raise Exception("No asset ID provided or found in invoice")
            
            # Convert asset ID to bytes
            asset_id_bytes = bytes.fromhex(asset_id)

            # Create the router payment request
            router_payment_request = router_pb2.SendPaymentRequest(
                payment_request=payment_request,
                fee_limit_sat=fee_limit_sats,
                timeout_seconds=60,
                no_inflight_updates=False
            )

            # Create taproot channel payment request
            request = tapchannel_pb2.SendPaymentRequest(
                payment_request=router_payment_request,
                asset_id=asset_id_bytes,
                allow_overpay=True
            )

            # Add peer_pubkey if provided
            if peer_pubkey:
                request.peer_pubkey = bytes.fromhex(peer_pubkey)
                logger.info(f"Using peer_pubkey: {peer_pubkey}")

            # Send payment and process stream responses
            logger.info(f"Sending payment for asset_id={asset_id}")
            response_stream = self.node.tapchannel_stub.SendPayment(request)
            
            # Process the stream responses
            preimage = ""
            fee_msat = 0
            status = "success"  # Default to success unless error occurs
            
            try:
                async for response in response_stream:
                    # Handle accepted sell order
                    if hasattr(response, 'accepted_sell_order') and response.HasField('accepted_sell_order'):
                        logger.info("Received accepted sell order response")
                        continue
                        
                    # Handle payment result
                    if hasattr(response, 'payment_result') and response.HasField('payment_result'):
                        result = response.payment_result
                        status_code = result.status if hasattr(result, 'status') else -1
                        
                        # Map status to action
                        if status_code == 2:  # SUCCEEDED
                            if hasattr(result, 'payment_preimage'):
                                preimage = result.payment_preimage.hex() if isinstance(result.payment_preimage, bytes) else str(result.payment_preimage)
                            
                            if hasattr(result, 'fee_msat'):
                                fee_msat = result.fee_msat
                                
                            logger.info(f"Payment succeeded: hash={payment_hash}, preimage={preimage}, fee={fee_msat//1000} sat")
                            
                        elif status_code == 3:  # FAILED
                            status = "failed"
                            failure_reason = result.failure_reason if hasattr(result, 'failure_reason') else "Unknown failure"
                            logger.error(f"Payment failed: {failure_reason}")
                            raise Exception(f"Payment failed: {failure_reason}")
                
                # Stream completed without error
                logger.info("Payment completed successfully")
                
            except grpc.aio.AioRpcError as e:
                # Check if the error appears to indicate payment in progress
                if any(msg in e.details().lower() for msg in ["payment initiated", "in progress", "in flight"]):
                    logger.info("Payment appears to be in progress, treating as potentially successful")
                else:
                    logger.error(f"gRPC error: {e.code()}: {e.details()}")
                    raise Exception(f"Payment error: {e.details()}")
            
            # Return successful response
            return {
                "payment_hash": payment_hash,
                "payment_preimage": preimage,
                "fee_sats": fee_msat // 1000,
                "status": status,
                "payment_request": payment_request
            }

        except Exception as e:
            logger.error(f"Payment failed: {str(e)}", exc_info=True)
            
            # Create user-friendly error message
            error_message = str(e).lower()
            if "multiple asset channels found" in error_message:
                detail = "Multiple channels found for this asset. Please select a specific channel."
            elif "no asset channel balance found" in error_message:
                detail = "Insufficient channel balance for this asset."
            else:
                detail = f"Failed to pay Taproot Asset invoice: {str(e)}"
                
            raise Exception(detail)

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
            logger.info(f"=== SETTLEMENT PROCESS STARTING ===")
            logger.info(f"Payment hash: {payment_hash}")
            logger.info(f"Asset ID: {asset_id}")

            # Retrieve the preimage for this payment hash
            preimage_hex = self.node._get_preimage(payment_hash)

            if not preimage_hex:
                logger.error(f"No preimage found for payment hash: {payment_hash}")
                raise Exception(f"Cannot settle HODL invoice: no preimage found for {payment_hash}")

            logger.info(f"Found preimage: {preimage_hex}")
            preimage_bytes = bytes.fromhex(preimage_hex)

            # Create settlement request
            from .taproot_transfers import direct_settle_invoice
            settlement_success = await direct_settle_invoice(self.node, payment_hash)

            if not settlement_success:
                logger.error(f"Failed to settle invoice for {payment_hash}")
                raise Exception("Settlement failed")

            logger.info("=== SETTLEMENT COMPLETED ===")
            return {
                "success": True,
                "payment_hash": payment_hash,
                "message": "HODL invoice settled successfully",
                "preimage": preimage_hex
            }

        except Exception as e:
            logger.error(f"Failed to update Taproot Assets after payment: {str(e)}", exc_info=True)
            raise Exception(f"Failed to update Taproot Assets: {str(e)}")
