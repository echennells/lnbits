from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from http import HTTPStatus
from pydantic import BaseModel

from lnbits.decorators import require_admin_key
from lnbits.core.models import WalletTypeInfo, Payment, CreateInvoice
from lnbits.nodes.tapd import TaprootAssetsNode

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
    """List all Taproot Assets."""
    node = TaprootAssetsNode()
    try:
        assets = await node.list_assets()
        await node.close()
        return assets
    except Exception as e:
        await node.close()
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
        # Create a Taproot Assets node
        node = TaprootAssetsNode()
        
        try:
            # Create the invoice using the RFQ process
            invoice_result = await node.create_asset_invoice(
                memo=data.memo or f"Taproot Asset Transfer",
                asset_id=data.asset_id,
                asset_amount=data.amount
            )
            
            await node.close()
            
            # Extract the payment hash and payment request
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]
            
            # Create extra data with Taproot Asset information
            extra = {
                "type": "taproot_asset",
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "buy_quote": invoice_result["accepted_buy_quote"]
            }
            
            # We need to decode the payment request to get the payment hash
            from lnbits import bolt11
            decoded = bolt11.decode(payment_request)
            
            # Create a payment record in the database
            from lnbits.core.crud import create_payment
            from lnbits.core.models import CreatePayment, PaymentState
            
            # Create payment model
            create_payment_model = CreatePayment(
                wallet_id=wallet.wallet.id,
                bolt11=payment_request,
                payment_hash=payment_hash,
                amount_msat=data.amount,  # For Taproot assets, we use the asset amount directly
                memo=data.memo or f"Taproot Asset Transfer",
                extra=extra,
                expiry=decoded.expiry_date,
            )
            
            # Create the payment
            payment = await create_payment(
                checking_id=payment_hash,
                data=create_payment_model,
            )
            
            # Return the invoice information with the accepted buy quote
            return {
                "payment_hash": payment_hash,
                "payment_request": payment_request,
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "accepted_buy_quote": invoice_result["accepted_buy_quote"],
                "checking_id": payment.checking_id
            }
        except Exception as e:
            await node.close()
            raise e
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Taproot Asset invoice: {str(e)}"
        )
