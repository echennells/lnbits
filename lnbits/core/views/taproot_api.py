from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from http import HTTPStatus
from pydantic import BaseModel

from lnbits.decorators import require_admin_key
from lnbits.core.models import WalletTypeInfo, Payment, CreateInvoice
from lnbits.wallets.taproot import TaprootAssetsWallet

# Use a consistent router prefix
taproot_router = APIRouter(prefix="/api/v1/taproot", tags=["Taproot Assets"])

# Define request model for Taproot Asset invoices
class TaprootInvoiceRequest(BaseModel):
    asset_id: str
    amount: int
    memo: Optional[str] = None
    expiry: Optional[int] = None

@taproot_router.get("/listassets", response_model=List[dict])
async def list_assets(wallet: WalletTypeInfo = Depends(require_admin_key)):
    """
    List all Taproot Assets, including those in Lightning channels.
    
    This endpoint retrieves all Taproot assets and combines them with asset information
    from Lightning channels with commitment type 4 or 6 (Taproot overlay).
    
    For assets that exist in channels, a `channel_info` field will be included with
    details about the channel, including capacity, balances, and channel point.
    
    Example response:
    ```json
    [
        {
            "name": "piratecoin",
            "asset_id": "b9ad8b868631ffe50fb09ff15e737fba9d4a34688a77ad608d3f6ee5db5eae44",
            "type": "0",
            "amount": "100",
            "genesis_point": "5dc88b161b7146e7e03dc916ba9b07575f9a1454bcb2ecc67dc063642007a244:0",
            "meta_hash": "70521e796c5550b5c6b5b3a10f2df6b6286fba213519a478e820e9818ddf5ce4",
            "version": "1",
            "is_spent": false,
            "script_key": "0250aaeb166f4234650d84a2d8a130987aeaf6950206e0905401ee74ff3f8d18e6",
            "channel_info": {
                "channel_point": "0433cf3f58bf26d0f7fb10917397e231bc25d57dba645cd3bbdbc837ee27cda3:0",
                "capacity": 100,
                "local_balance": 85,
                "remote_balance": 15
            }
        }
    ]
    ```
    """
    taproot_wallet = TaprootAssetsWallet()
    try:
        # Create a node instance
        node = taproot_wallet.__node_cls__(wallet=taproot_wallet)
        
        # Get assets
        assets = await node.list_assets()
        await node.close()
        return assets
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
            detail=f"Failed to list assets: {str(e)}"
        )

@taproot_router.post("/invoice", response_model=dict)
async def create_taproot_invoice(
    data: TaprootInvoiceRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key)
):
    """Create an invoice for a Taproot Asset."""
    try:
        print(f"DEBUG:taproot_api:Creating Taproot Asset invoice for asset_id={data.asset_id}, amount={data.amount}")
        
        # Create a TaprootAssetsWallet instance
        taproot_wallet = TaprootAssetsWallet()
        
        # Create the invoice directly using the TaprootAssetsWallet
        try:
            # First, create the invoice using the TaprootAssetsWallet
            invoice_response = await taproot_wallet.create_invoice(
                amount=data.amount,
                memo=data.memo or "Taproot Asset Transfer",
                asset_id=data.asset_id
            )
            
            if not invoice_response.ok:
                raise Exception(f"Failed to create invoice: {invoice_response.error_message}")
            
            # Extract the original payment_request and payment_hash from the tapd response
            original_payment_request = invoice_response.payment_request
            original_payment_hash = invoice_response.checking_id  # The payment_hash is stored in the checking_id field
            
            print(f"DEBUG:taproot_api:Got original payment_request from tapd: {original_payment_request}")
            print(f"DEBUG:taproot_api:Got original payment_hash from tapd: {original_payment_hash}")
            
            # Extract buy_quote if it exists
            buy_quote = {}
            if invoice_response.extra and "buy_quote" in invoice_response.extra:
                buy_quote = invoice_response.extra["buy_quote"]
            
            # Parse the original BOLT11 invoice to get the correct satoshi amount
            from lnbits import bolt11
            try:
                decoded_invoice = bolt11.decode(original_payment_request)
                satoshi_amount_msat = decoded_invoice.amount_msat
                satoshi_amount = satoshi_amount_msat // 1000 if satoshi_amount_msat is not None else 0
                print(f"DEBUG:taproot_api:Decoded original invoice, satoshi_amount={satoshi_amount} sats ({satoshi_amount_msat} msats)")
            except Exception as e:
                print(f"DEBUG:taproot_api:Error decoding original invoice: {e}")
                satoshi_amount = data.amount  # Fallback to asset amount if decoding fails
                satoshi_amount_msat = data.amount * 1000
            
            # Now create a payment record in the database using the original invoice details
            from lnbits.core.services import create_invoice
            
            # Create the payment with the original BOLT11 invoice and correct satoshi amount
            payment = await create_invoice(
                wallet_id=wallet.wallet.id,
                amount=satoshi_amount,  # Use the correct satoshi amount from the original invoice
                memo=data.memo or "Taproot Asset Transfer",
                extra={
                    "type": "taproot_asset",
                    "asset_id": data.asset_id,
                    "asset_amount": data.amount,
                    "buy_quote": buy_quote,
                    "payment_request": original_payment_request,  # Pass the original BOLT11 invoice
                    "payment_hash": original_payment_hash  # Pass the original payment hash
                },
                expiry=data.expiry
            )
            
            print(f"DEBUG:taproot_api:Payment created successfully: payment_hash={payment.payment_hash}")
            print(f"DEBUG:taproot_api:Payment object: {payment}")
            print(f"DEBUG:taproot_api:Payment extra data: {payment.extra}")
        except Exception as e:
            print(f"DEBUG:taproot_api:Error creating invoice: {e}")
            print(f"DEBUG:taproot_api:Error type: {type(e)}")
            raise
        
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
        
        # Extract the accepted_buy_quote from the extra data
        # Ensure it's a simple dict that can be JSON serialized
        try:
            # Get the buy_quote from extra data
            accepted_buy_quote = payment.extra.get("buy_quote", {})
            
            # Ensure it's a serializable dict
            accepted_buy_quote = ensure_serializable(accepted_buy_quote)
            
            print(f"DEBUG:taproot_api:Payment extra data: {payment.extra}")
            print(f"DEBUG:taproot_api:Extracted accepted_buy_quote: {accepted_buy_quote}")
            
            # Check if we have a buy_quote in the extra data
            if "buy_quote" in payment.extra:
                print(f"DEBUG:taproot_api:buy_quote is present in extra data")
            else:
                print(f"DEBUG:taproot_api:buy_quote is NOT present in extra data")
            
            # Create a response with all serializable values
            response_data = ensure_serializable({
                "payment_hash": payment.payment_hash,
                "payment_request": payment.bolt11,  # Use the original BOLT11 invoice
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "satoshi_amount": satoshi_amount,  # Include the satoshi amount for clarity
                "accepted_buy_quote": accepted_buy_quote,
                "checking_id": payment.checking_id
            })
        except Exception as e:
            print(f"DEBUG:taproot_api:Error processing accepted_buy_quote: {e}")
            # Fallback to a simpler response without the problematic field
            response_data = {
                "payment_hash": payment.payment_hash,
                "payment_request": payment.bolt11,  # Use the original BOLT11 invoice
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "accepted_buy_quote": {},
                "checking_id": payment.checking_id
            }
        
        print(f"DEBUG:taproot_api:Returning response: {response_data}")
        return response_data
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Taproot Asset invoice: {str(e)}"
        )
