"""
Balance-related CRUD operations for Taproot Assets extension.
"""
from typing import List, Optional
from datetime import datetime

from lnbits.helpers import urlsafe_short_hash

from ..models import AssetBalance
from ..db import db, get_table_name
from ..db_utils import with_transaction

async def get_asset_balance(wallet_id: str, asset_id: str, conn=None) -> Optional[AssetBalance]:
    """
    Get asset balance for a specific wallet and asset.
    
    Args:
        wallet_id: The wallet ID to get the balance for
        asset_id: The asset ID to get the balance for
        conn: Optional database connection to reuse
        
    Returns:
        Optional[AssetBalance]: The asset balance if found, None otherwise
    """
    return await (conn or db).fetchone(
        f"""
        SELECT * FROM {get_table_name('asset_balances')}
        WHERE wallet_id = :wallet_id AND asset_id = :asset_id
        """,
        {
            "wallet_id": wallet_id,
            "asset_id": asset_id
        },
        AssetBalance
    )


async def get_wallet_asset_balances(wallet_id: str) -> List[AssetBalance]:
    """
    Get all asset balances for a wallet.
    
    Args:
        wallet_id: The wallet ID to get balances for
        
    Returns:
        List[AssetBalance]: List of asset balances for the wallet
    """
    return await db.fetchall(
        f"""
        SELECT * FROM {get_table_name('asset_balances')}
        WHERE wallet_id = :wallet_id
        ORDER BY updated_at DESC
        """,
        {"wallet_id": wallet_id},
        AssetBalance
    )


@with_transaction
async def update_asset_balance(
    wallet_id: str,
    asset_id: str,
    amount_change: int,
    payment_hash: Optional[str] = None,
    conn=None
) -> Optional[AssetBalance]:
    """
    Update asset balance, creating it if it doesn't exist.
    
    Args:
        wallet_id: The wallet ID to update the balance for
        asset_id: The asset ID to update the balance for
        amount_change: The amount to change the balance by (positive or negative)
        payment_hash: Optional payment hash to associate with the balance update
        conn: Optional database connection to reuse
        
    Returns:
        Optional[AssetBalance]: The updated asset balance
    """
    now = datetime.now()
    
    # Check if balance exists
    balance = await get_asset_balance(wallet_id, asset_id, conn)
    
    if balance:
        # Update existing balance
        balance.balance += amount_change
        if payment_hash:
            balance.last_payment_hash = payment_hash
        balance.updated_at = now
        
        # Update in database using standardized method
        await conn.update(
            get_table_name("asset_balances"),
            balance,
            "WHERE wallet_id = :wallet_id AND asset_id = :asset_id"
        )
    else:
        # Create new balance
        balance_id = urlsafe_short_hash()
        balance = AssetBalance(
            id=balance_id,
            wallet_id=wallet_id,
            asset_id=asset_id,
            balance=amount_change,
            last_payment_hash=payment_hash,
            created_at=now,
            updated_at=now
        )
        
        # Insert new balance using standardized method
        await conn.insert(get_table_name("asset_balances"), balance)
    
    # Return the updated balance
    return await get_asset_balance(wallet_id, asset_id, conn)
