"""
Payment-related CRUD operations for Taproot Assets extension.
"""
from typing import List, Optional
from datetime import datetime

from lnbits.helpers import urlsafe_short_hash

from ..models import TaprootPayment
from ..db import db, get_table_name
from ..db_utils import with_transaction
from .utils import get_records_by_field

@with_transaction
async def create_payment_record(
    payment_hash: str, 
    payment_request: str,
    asset_id: str, 
    asset_amount: int,
    fee_sats: int,
    user_id: str,
    wallet_id: str,
    description: Optional[str] = None,
    preimage: Optional[str] = None,
    conn=None
) -> TaprootPayment:
    """
    Create a record of a sent payment.
    
    Args:
        payment_hash: The payment hash
        payment_request: The payment request (BOLT11 invoice)
        asset_id: The asset ID
        asset_amount: The amount of the asset
        fee_sats: The fee in satoshis
        user_id: The user ID
        wallet_id: The wallet ID
        description: Optional description
        preimage: Optional payment preimage
        conn: Optional database connection to reuse
        
    Returns:
        TaprootPayment: The created payment record
    """
    now = datetime.now()
    payment_id = urlsafe_short_hash()
    
    # Create the payment model
    payment = TaprootPayment(
        id=payment_id,
        payment_hash=payment_hash,
        payment_request=payment_request,
        asset_id=asset_id,
        asset_amount=asset_amount,
        fee_sats=fee_sats,
        description=description,
        status="completed",
        user_id=user_id,
        wallet_id=wallet_id,
        created_at=now,
        preimage=preimage
    )
    
    # Insert using standardized method
    await conn.insert(get_table_name("payments"), payment)
    
    return payment


async def get_user_payments(user_id: str) -> List[TaprootPayment]:
    """
    Get all sent payments for a user.
    
    Args:
        user_id: The user ID to get payments for
        
    Returns:
        List[TaprootPayment]: List of payments for the user
    """
    return await get_records_by_field("payments", "user_id", user_id, TaprootPayment)
