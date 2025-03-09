from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from http import HTTPStatus
from pydantic import BaseModel

from lnbits.decorators import require_admin_key
from lnbits.core.models import WalletTypeInfo, Payment, CreateInvoice
from lnbits.nodes.tapd import TaprootAssetsNode

taproot_router = APIRouter(prefix="/api/v1/taproot", tags=["Taproot Assets"])

class TaprootInvoiceRequest(BaseModel):
    asset_id: str
    amount: int
    memo: Optional[str] = None
    expiry: Optional[int] = None

@taproot_router.get("/listassets", response_model=List[dict])
async def list_assets(wallet: WalletTypeInfo = Depends(require_admin_key)):
    """List all Lightning channels with Taproot assets."""
    node = TaprootAssetsNode()
    try:
        # Use the direct method which is working correctly
        channels = await node.list_channel_assets_direct()
        await node.close()
        return channels
    except Exception as e:
        await node.close()
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to list channels: {str(e)}"
        )

@taproot_router.get("/debug", response_model=dict)
async def debug_channel_data(wallet: WalletTypeInfo = Depends(require_admin_key)):
    """Debug function to print detailed information about the custom_channel_data."""
    node = TaprootAssetsNode()
    try:
        debug_info = await node.debug_channel_data()
        await node.close()
        return debug_info
    except Exception as e:
        await node.close()
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to debug channel data: {str(e)}"
        )

@taproot_router.get("/listassets_direct", response_model=List[dict])
async def list_assets_direct(wallet: WalletTypeInfo = Depends(require_admin_key)):
    """Alternative approach: Get asset information directly from the TAP RPC."""
    node = TaprootAssetsNode()
    try:
        channels = await node.list_channel_assets_direct()
        await node.close()
        return channels
    except Exception as e:
        await node.close()
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to list channel assets: {str(e)}"
        )

@taproot_router.post("/invoice", response_model=dict)
async def create_taproot_invoice(
    data: TaprootInvoiceRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key)
):
    try:
        node = TaprootAssetsNode()
        try:
            invoice_result = await node.create_asset_invoice(
                memo=data.memo or f"Taproot Asset Transfer",
                asset_id=data.asset_id,
                asset_amount=data.amount
            )
            await node.close()

            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]

            extra = {
                "type": "taproot_asset",
                "asset_id": data.asset_id,
                "asset_amount": data.amount,
                "buy_quote": invoice_result["accepted_buy_quote"]
            }

            from lnbits import bolt11
            decoded = bolt11.decode(payment_request)

            from lnbits.core.crud import create_payment
            from lnbits.core.models import CreatePayment

            create_payment_model = CreatePayment(
                wallet_id=wallet.wallet.id,
                bolt11=payment_request,
                payment_hash=payment_hash,
                amount_msat=data.amount,
                memo=data.memo or f"Taproot Asset Transfer",
                extra=extra,
                expiry=decoded.expiry_date,
            )

            payment = await create_payment(
                checking_id=payment_hash,
                data=create_payment_model,
            )

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

