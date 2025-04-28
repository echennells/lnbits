"""
Payment-related CRUD operations for Taproot Assets extension.
"""
from typing import List, Optional
from datetime import datetime

from lnbits.helpers import urlsafe_short_hash

from ..models import TaprootPayment, FeeTransaction
from ..db import db, get_table_name
from .utils import get_records_by_field

async def create_payment_record(
    payment_hash: str, 
    payment_request: str,
    asset_id: str, 
    asset_amount: int,
    fee_sats: int,
    user_id: str,
    wallet_id: str,
    memo: Optional[str] = None,
    preimage: Optional[str] = None
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
        memo: Optional memo
        preimage: Optional payment preimage
        
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
        memo=memo,
        status="completed",
        user_id=user_id,
        wallet_id=wallet_id,
        created_at=now,
        preimage=preimage
    )
    
    # Insert using standardized method
    await db.insert(get_table_name("payments"), payment)
    
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


async def create_fee_transaction(
    user_id: str,
    wallet_id: str,
    asset_payment_hash: str,
    fee_amount_msat: int,
    status: str
) -> FeeTransaction:
    """
    Create a record of a satoshi fee transaction.
    
    Args:
        user_id: The user ID
        wallet_id: The wallet ID
        asset_payment_hash: The payment hash of the asset transaction
        fee_amount_msat: The fee amount in millisatoshis
        status: The status of the fee transaction
        
    Returns:
        FeeTransaction: The created fee transaction record
    """
    transaction_id = urlsafe_short_hash()
    now = datetime.now()
    
    # Create the transaction object
    fee_transaction = FeeTransaction(
        id=transaction_id,
        user_id=user_id,
        wallet_id=wallet_id,
        asset_payment_hash=asset_payment_hash,
        fee_amount_msat=fee_amount_msat,
        status=status,
        created_at=now
    )
    
    # Insert using standardized method
    await db.insert(get_table_name("fee_transactions"), fee_transaction)
    
    return fee_transaction


async def get_fee_transactions(user_id: Optional[str] = None) -> List[FeeTransaction]:
    """
    Get fee transactions, optionally filtered by user ID.
    
    Args:
        user_id: Optional user ID to filter by
        
    Returns:
        List[FeeTransaction]: List of fee transactions
    """
    if user_id:
        return await get_records_by_field("fee_transactions", "user_id", user_id, FeeTransaction)
    else:
        return await db.fetchall(
            f"SELECT * FROM {get_table_name('fee_transactions')} ORDER BY created_at DESC",
            {},
            FeeTransaction
        )
