"""
Unified Transaction Service for Taproot Assets extension.
This service encapsulates all transaction recording and balance updating logic.
"""
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime

from lnbits.helpers import urlsafe_short_hash

from ..models import AssetTransaction, AssetBalance
from ..db_utils import transaction, with_transaction
from ..logging_utils import log_info, log_error, TRANSFER
from ..error_utils import ErrorContext
from ..db import db, get_table_name

class TransactionService:
    """
    Unified service for handling all asset transaction operations.
    This service encapsulates all transaction recording and balance updating logic.
    """
    
    @staticmethod
    @with_transaction
    async def record_transaction(
        wallet_id: str,
        asset_id: str,
        amount: int,
        tx_type: str,
        payment_hash: Optional[str] = None,
        fee: int = 0,
        description: Optional[str] = None,
        create_tx_record: bool = True,
        conn=None
    ) -> Tuple[bool, Optional[AssetTransaction], Optional[AssetBalance]]:
        """
        Unified method to record transactions and update balances.
        
        Args:
            wallet_id: The wallet ID
            asset_id: The asset ID
            amount: The transaction amount
            tx_type: The transaction type ('credit' or 'debit')
            payment_hash: Optional payment hash
            fee: Optional fee amount
            description: Optional description
            create_tx_record: Whether to create a transaction record (True) or just update balance (False)
            conn: Optional database connection
            
        Returns:
            Tuple containing:
                - Success status (bool)
                - Transaction record if created, None otherwise
                - Updated balance record
        """
        with ErrorContext("record_transaction", TRANSFER):
            try:
                now = datetime.now()
                tx = None
                
                # For debit, amount should be negative for balance update
                balance_change = amount if tx_type == 'credit' else -amount
                
                # Step 1: Create transaction record if requested
                if create_tx_record:
                    tx_id = urlsafe_short_hash()
                    tx = AssetTransaction(
                        id=tx_id,
                        wallet_id=wallet_id,
                        asset_id=asset_id,
                        payment_hash=payment_hash,
                        amount=amount,
                        fee=fee,
                        description=description,
                        type=tx_type,
                        created_at=now
                    )
                    
                    # Insert transaction record
                    await conn.insert(get_table_name("asset_transactions"), tx)
                    log_info(TRANSFER, f"Transaction record created: {tx_id} for wallet {wallet_id}")
                
                # Step 2: Get current balance
                balance = await TransactionService.get_asset_balance(wallet_id, asset_id, conn=conn)
                
                # Step 3: Update or create balance
                if balance:
                    # Update existing balance
                    balance.balance += balance_change
                    if payment_hash:
                        balance.last_payment_hash = payment_hash
                    balance.updated_at = now
                    
                    # Update in database
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
                        balance=balance_change,
                        last_payment_hash=payment_hash,
                        created_at=now,
                        updated_at=now
                    )
                    
                    # Insert new balance
                    await conn.insert(get_table_name("asset_balances"), balance)
                
                log_info(TRANSFER, f"Balance updated for wallet {wallet_id}, asset {asset_id}: {balance_change}")
                return True, tx, balance
                
            except Exception as e:
                log_error(TRANSFER, f"Failed to record transaction: {str(e)}")
                return False, None, None
    
    @staticmethod
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
    
    @staticmethod
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
    
    @staticmethod
    async def get_asset_transactions(
        wallet_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AssetTransaction]:
        """
        Get asset transactions, optionally filtered by wallet and/or asset.
        
        Args:
            wallet_id: Optional wallet ID to filter by
            asset_id: Optional asset ID to filter by
            limit: Maximum number of transactions to return
            
        Returns:
            List[AssetTransaction]: List of asset transactions
        """
        # Build query
        query = f"SELECT * FROM {get_table_name('asset_transactions')}"
        params = {}
        where_clauses = []

        if wallet_id:
            where_clauses.append("wallet_id = :wallet_id")
            params["wallet_id"] = wallet_id

        if asset_id:
            where_clauses.append("asset_id = :asset_id")
            params["asset_id"] = asset_id

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        return await db.fetchall(query, params, AssetTransaction)
