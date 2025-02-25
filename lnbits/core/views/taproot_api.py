from fastapi import APIRouter, Depends, HTTPException
from typing import List
from pydantic import BaseModel

from lnbits.decorators import require_admin_key
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import create_invoice
from lnbits.nodes.tapd import TaprootAssetsNode

taproot_router = APIRouter(
    prefix="/taproot/api/v1",
    tags=["Taproot Assets"]
)

class CreateTaprootInvoice(BaseModel):
    wallet_id: str
    asset_id: str
    amount: float
    memo: str = ""
    currency: str = "sat"

@taproot_router.get("/assets", response_model=List[dict])
async def list_assets(wallet: WalletTypeInfo = Depends(require_admin_key)):
    """List all Taproot Assets."""
    node = TaprootAssetsNode()
    try:
        assets = await node.list_assets()
        await node.close()
        return assets
    except Exception as e:
        await node.close()
        raise HTTPException(status_code=500, detail=f"Failed to list assets: {str(e)}")

@taproot_router.post("/invoice")
async def create_taproot_invoice(
    data: CreateTaprootInvoice,
    wallet: WalletTypeInfo = Depends(require_admin_key)
):
    """Create an invoice that includes Taproot Asset information."""
    try:
        # Verify the asset exists
        node = TaprootAssetsNode()
        assets = await node.list_assets()
        await node.close()
        
        asset = next((a for a in assets if a["asset_id"] == data.asset_id), None)
        if not asset:
            raise HTTPException(
                status_code=404,
                detail=f"Asset with ID {data.asset_id} not found"
            )

        # Create standard LNbits invoice with Taproot Asset info in extra field
        invoice = await create_invoice(
            wallet_id=data.wallet_id,
            amount=data.amount,
            memo=data.memo,
            currency=data.currency,
            extra={
                "type": "taproot_asset",
                "asset_id": data.asset_id
            }
        )
        
        return {
            "payment_hash": invoice.payment_hash,
            "payment_request": invoice.bolt11,
            "checking_id": invoice.checking_id,
            "asset_id": data.asset_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")
