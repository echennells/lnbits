import hashlib
import time
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
    router_pb2,
    invoices_pb2
)

# Import WebSocket manager
from ..websocket import ws_manager
from ..crud import (
    create_payment_record, 
    record_asset_transaction, 
    get_asset_balance, 
    get_invoice_by_payment_hash, 
    is_internal_payment,
    is_self_payment,
    update_invoice_status
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
                
                # Extract asset ID from invoice description if not provided
                if not asset_id and hasattr(decoded, 'description'):
                    desc = decoded.description
                    logger.info(f"Checking description: {desc}")
                    if desc and 'asset_id=' in desc:
                        asset_id_match = re.search(r'asset_id=([a-fA-F0-9]{64})', desc)
                        if asset_id_match:
                            asset_id = asset_id_match.group(1)
                            logger.info(f"Extracted asset_id from description: {asset_id}")
            except Exception as e:
                logger.error(f"Failed to decode invoice: {str(e)}")
                raise Exception(f"Invalid invoice format: {str(e)}")

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

            # Verify we have required parameters
            if not payment_hash:
                raise Exception("Could not extract payment hash from invoice")
                
            if not asset_id:
                raise Exception("No asset ID provided or found in invoice")
            
            # Check if this is an internal payment (invoice belongs to any user on this node)
            # This check should be done at the API layer, but we include it here as an additional safety check
            is_internal = await is_internal_payment(payment_hash)
            if is_internal:
                logger.warning(f"Detected internal payment attempt for hash {payment_hash}. This should be handled by update_after_payment.")
                raise Exception("Internal payments (to another user on this node) should be handled through the internal-payment endpoint.")

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
            
            try:
                response_stream = self.node.tapchannel_stub.SendPayment(request)
            except grpc.aio.AioRpcError as e:
                logger.error(f"gRPC error starting payment: {e.code()}: {e.details()}")
                raise Exception(f"Failed to start payment: {e.details()}")
            
            # Process the stream responses
            preimage = ""
            fee_msat = 0
            status = "success"  # Default to success unless error occurs
            accepted_sell_order_seen = False
            
            try:
                async for response in response_stream:
                    # Handle accepted sell order
                    if hasattr(response, 'accepted_sell_order') and response.HasField('accepted_sell_order'):
                        logger.info("Received accepted sell order response")
                        accepted_sell_order_seen = True
                        continue
                        
                    # Handle payment result
                    if hasattr(response, 'payment_result') and response.HasField('payment_result'):
                        result = response.payment_result
                        status_code = result.status if hasattr(result, 'status') else -1
                        
                        # Map status code to action
                        if status_code == 2:  # SUCCEEDED
                            if hasattr(result, 'payment_preimage'):
                                preimage = result.payment_preimage.hex() if isinstance(result.payment_preimage, bytes) else str(result.payment_preimage)
                            
                            if hasattr(result, 'fee_msat'):
                                fee_msat = result.fee_msat
                                
                            logger.info(f"Payment succeeded: hash={payment_hash}, fee={fee_msat//1000} sat")
                            
                        elif status_code == 3:  # FAILED
                            status = "failed"
                            failure_reason = result.failure_reason if hasattr(result, 'failure_reason') else "Unknown failure"
                            logger.error(f"Payment failed: {failure_reason}")
                            raise Exception(f"Payment failed: {failure_reason}")
                
                # Stream completed without explicit error
                logger.info("Payment stream completed")
                
                # If we've seen an accepted_sell_order but no final status,
                # consider it potentially successful
                if accepted_sell_order_seen and status != "failed":
                    logger.info("Payment appears to be in progress (saw accepted sell order)")
                    status = "success"
                
            except grpc.aio.AioRpcError as e:
                # Check if the error indicates payment in progress
                error_str = e.details().lower()
                if any(msg in error_str for msg in ["payment initiated", "in progress", "in flight"]):
                    logger.info("Payment appears to be in progress, treating as potentially successful")
                    status = "success"
                elif "self-payments not allowed" in error_str:
                    # Catch the self-payment error specifically
                    logger.warning(f"Self-payment detected for {payment_hash} - this should be handled by update_after_payment")
                    raise Exception("Self-payments are not allowed through the regular payment flow. Use the internal-payment endpoint.")
                else:
                    logger.error(f"gRPC error in payment stream: {e.code()}: {e.details()}")
                    raise Exception(f"Payment error: {e.details()}")
            except Exception as e:
                if accepted_sell_order_seen:
                    # If we've seen an accepted_sell_order, the payment might still succeed
                    logger.info(f"Payment stream ended with error after accepted_sell_order: {str(e)}")
                    logger.info("Considering payment as potentially successful")
                    status = "success"
                else:
                    logger.error(f"Error in payment stream: {str(e)}")
                    raise Exception(f"Payment error: {str(e)}")
            
            # Get the asset amount from decoded invoice
            asset_amount = decoded.amount_msat // 1000 if hasattr(decoded, "amount_msat") else 0
            
            # Return response with all available information
            return {
                "payment_hash": payment_hash,
                "payment_preimage": preimage,
                "fee_sats": fee_msat // 1000,
                "status": status,
                "payment_request": payment_request,
                "asset_id": asset_id,
                "asset_amount": asset_amount
            }

        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC error in pay_asset_invoice: {e.code()}: {e.details()}")
            
            # Create user-friendly error message
            error_details = e.details().lower()
            if "multiple asset channels found" in error_details:
                detail = "Multiple channels found for this asset. Please select a specific channel."
            elif "no asset channel balance found" in error_details:
                detail = "Insufficient channel balance for this asset."
            elif "self-payments not allowed" in error_details:
                detail = "Self-payments are not allowed. This invoice belongs to you and needs to be processed through the self-payment flow."
            else:
                detail = f"gRPC error: {e.details()}"
                
            raise Exception(detail)
            
        except Exception as e:
            logger.error(f"Payment failed: {str(e)}")
            raise Exception(f"Failed to pay Taproot Asset invoice: {str(e)}")

    async def update_after_payment(
        self,
        payment_request: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update Taproot Assets after a payment has been made through the LNbits wallet.

        This method is specifically used for internal payments (including self-payments) to update 
        the Taproot Assets daemon about internal transfers without requiring an actual
        Lightning Network payment.

        Args:
            payment_request: The original BOLT11 invoice
            payment_hash: The payment hash of the completed payment
            fee_limit_sats: Optional fee limit in satoshis (not used for actual payment now)
            asset_id: Optional asset ID to use for the update

        Returns:
            Dict containing the update confirmation
        """
        try:
            logger.info(f"=== INTERNAL PAYMENT PROCESS STARTING ===")
            logger.info(f"Payment hash: {payment_hash}")
            logger.info(f"Asset ID: {asset_id or 'Not specified'}")

            # Verify this is actually an internal payment
            invoice = await get_invoice_by_payment_hash(payment_hash)
            if not invoice:
                logger.error(f"No invoice found for payment hash: {payment_hash}")
                raise Exception(f"Invoice not found for payment hash: {payment_hash}")
                
            # Get the wallet information from the node
            if not hasattr(self.node, 'wallet') or not self.node.wallet:
                logger.error("Node has no wallet information")
                raise Exception("Wallet information missing from node")
            
            # Ensure we have asset_id (either provided or from the invoice)
            if not asset_id:
                asset_id = invoice.asset_id
                logger.info(f"Using asset_id from invoice: {asset_id}")

            # Get or generate a preimage for this payment hash
            preimage_hex = self.node._get_preimage(payment_hash)
            if not preimage_hex:
                logger.info(f"No preimage found for payment hash: {payment_hash}, generating one")
                # Generate a preimage if one doesn't exist
                preimage = hashlib.sha256(f"{payment_hash}_{time.time()}".encode()).digest()
                preimage_hex = preimage.hex()
                # Store it
                self.node._store_preimage(payment_hash, preimage_hex)
            
            logger.info(f"Using preimage: {preimage_hex}")

            # Process as an internal payment - first handle the receiver's side
            # Check if this is a self-payment (same user) or an internal payment (different user)
            is_self_pay = invoice.user_id == self.node.wallet.user
            
            # CRITICAL FIX: Call settle_internal_payment to handle the receiver's credit transaction
            # Use the transfer_manager's settle_internal_payment method
            success = await self.node.transfer_manager.settle_internal_payment(self.node, payment_hash)
            if not success:
                logger.error(f"Failed to process receiver's transaction")
                raise Exception("Failed to update receiver's balance")
                
            # Sender: Record debit transaction and update balance
            user_id = self.node.wallet.user
            wallet_id = self.node.wallet.id
            
            # Create descriptive memo based on payment type
            if is_self_pay:
                memo = f"Self-payment: {invoice.memo or 'Taproot Asset Transfer'}"
            else:
                memo = f"Internal payment to {invoice.user_id}: {invoice.memo or 'Taproot Asset Transfer'}"
            
            try:
                # First record the debit transaction for the sender
                debit_tx = await record_asset_transaction(
                    wallet_id=wallet_id,
                    asset_id=asset_id,
                    amount=invoice.asset_amount,
                    tx_type="debit",  # This is an outgoing payment
                    payment_hash=payment_hash,
                    memo=memo
                )
                
                # Record the payment in the payments table
                payment_record = await create_payment_record(
                    payment_hash=payment_hash,
                    payment_request=payment_request,
                    asset_id=asset_id,
                    asset_amount=invoice.asset_amount,
                    fee_sats=0,  # No fee for internal payments
                    user_id=user_id,
                    wallet_id=wallet_id,
                    memo=memo,
                    preimage=preimage_hex
                )
                
                # Send payment update via WebSocket
                if payment_record:
                    payment_data = {
                        "id": payment_record.id,
                        "payment_hash": payment_hash,
                        "asset_id": asset_id,
                        "asset_amount": invoice.asset_amount,
                        "fee_sats": 0,
                        "memo": memo,
                        "status": "completed",
                        "created_at": payment_record.created_at.isoformat() if hasattr(payment_record.created_at, "isoformat") else str(payment_record.created_at),
                        "internal_payment": True,
                        "self_payment": is_self_pay
                    }
                    await ws_manager.notify_payment_update(user_id, payment_data)
            except Exception as db_error:
                logger.error(f"Failed to create payment record for internal payment: {str(db_error)}")
            
            # Update assets balances via WebSocket
            try:
                assets = await self.node.list_assets()
                filtered_assets = [asset for asset in assets if asset.get("channel_info")]
                
                # Add balance information
                for asset in filtered_assets:
                    asset_id_check = asset.get("asset_id")
                    if asset_id_check:
                        asset_balance = await get_asset_balance(wallet_id, asset_id_check)
                        asset["user_balance"] = asset_balance.balance if asset_balance else 0
                
                if filtered_assets:
                    await ws_manager.notify_assets_update(user_id, filtered_assets)
            except Exception as asset_err:
                logger.error(f"Failed to fetch assets for WebSocket update: {str(asset_err)}")
            
            logger.info("=== DATABASE UPDATES COMPLETED ===")
            
            # Return response with appropriate flags
            response = {
                "success": True,
                "payment_hash": payment_hash,
                "message": "Internal payment processed successfully",
                "preimage": preimage_hex,
                "asset_id": asset_id,
                "asset_amount": invoice.asset_amount,
                "internal_payment": True
            }
            
            # Add self_payment flag if it's a self-payment
            if is_self_pay:
                response["self_payment"] = True
            
            return response

        except Exception as e:
            logger.error(f"Failed to process internal payment: {str(e)}")
            raise Exception(f"Failed to update Taproot Assets: {str(e)}")
