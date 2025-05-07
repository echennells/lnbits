"""
Transaction-related CRUD operations for Taproot Assets extension.
"""
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from loguru import logger

from lnbits.helpers import urlsafe_short_hash

from ..models import AssetTransaction, TaprootInvoice, AssetBalance
from ..db import db, get_table_name
from ..db_utils import transaction, with_transaction
from .balances import get_asset_balance
from .invoices import get_invoice_by_payment_hash, update_invoice_status

@with_transaction
async def record_asset_transaction(
    wallet_id: str,
    asset_id: str,
    amount: int,
    tx_type: str,  # 'credit' or 'debit'
    payment_hash: Optional[str] = None,
    fee: int = 0,
    memo: Optional[str] = None,
    conn=None
) -> AssetTransaction:
    """
    Record an asset transaction and update the balance atomically.
    
    Args:
        wallet_id: The wallet ID for the transaction
        asset_id: The asset ID for the transaction
        amount: The amount of the asset
        tx_type: The type of transaction ('credit' or 'debit')
        payment_hash: Optional payment hash for the transaction
        fee: Optional fee amount
        memo: Optional memo for the transaction
        conn: Optional database connection to reuse
        
    Returns:
        AssetTransaction: The recorded transaction
    """
    now = datetime.now()
    tx_id = urlsafe_short_hash()
    
    # Create transaction record
    tx = AssetTransaction(
        id=tx_id,
        wallet_id=wallet_id,
        asset_id=asset_id,
        payment_hash=payment_hash,
        amount=amount,
        fee=fee,
        memo=memo,
        type=tx_type,
        created_at=now
    )
    
    # Insert transaction record using standardized method
    await conn.insert(get_table_name("asset_transactions"), tx)
    
    # Update balance
    # For debit, amount should be negative for balance update
    balance_change = amount if tx_type == 'credit' else -amount
    
    # Check if balance exists
    balance = await get_asset_balance(wallet_id, asset_id, conn=conn)
    
    if balance:
        # Update existing balance
        balance.balance += balance_change
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
            balance=balance_change,
            last_payment_hash=payment_hash,
            created_at=now,
            updated_at=now
        )
        
        # Insert new balance using standardized method
        await conn.insert(get_table_name("asset_balances"), balance)
    
    return tx


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


@with_transaction
async def record_settlement_transaction(
    invoice: TaprootInvoice, 
    payment_hash: str,
    conn=None
) -> Tuple[bool, Optional[AssetTransaction], Optional[str]]:
    """
    Record the asset transaction for a settlement.
    
    Args:
        invoice: The invoice being settled
        payment_hash: The payment hash
        conn: Optional database connection to reuse
        
    Returns:
        Tuple containing:
        - success (bool): Whether transaction recording was successful
        - transaction (Optional[AssetTransaction]): The recorded transaction if successful
        - error_message (Optional[str]): Error message if recording fails
    """
    try:
        # Use the memo directly from the invoice without setting a default
        tx = await record_asset_transaction(
            wallet_id=invoice.wallet_id,
            asset_id=invoice.asset_id,
            amount=invoice.asset_amount,
            tx_type="credit",
            payment_hash=payment_hash,
            memo=invoice.memo,
            conn=conn
        )
        
        return True, tx, None
    except Exception as e:
        error_msg = f"Failed to record transaction: {str(e)}"
        logger.error(error_msg)
        return False, None, error_msg


# Define types for settlement response
SettlementResponse = Dict[str, Any]

async def process_settlement_transaction(
    payment_hash: str,
    user_id: str,
    wallet_id: str,
    update_status: bool = True,
    notify_websocket: bool = True
) -> SettlementResponse:
    """
    Process a settlement transaction for a Taproot Asset invoice.
    
    This function handles the full settlement process when an invoice is paid,
    including validating the invoice, updating its status, and recording the 
    asset transaction with proper balance updates.
    
    Args:
        payment_hash: The payment hash of the invoice to settle
        user_id: User ID for the invoice owner
        wallet_id: Wallet ID for the invoice owner
        update_status: Whether to update the invoice status to "paid"
        notify_websocket: Whether to send WebSocket notifications (handled externally)
        
    Returns:
        SettlementResponse: A dictionary containing:
            - success (bool): Whether the settlement was successful
            - message (str): A human-readable message describing the result
            - invoice (Optional[Dict]): The invoice data if available
            - asset_id (Optional[str]): The asset ID for the settled invoice
            - asset_amount (Optional[int]): The asset amount for the settled invoice
            - tx_id (Optional[str]): Transaction ID if a transaction was recorded
            - error (Optional[str]): Error message if settlement failed
            - payment_hash (str): The payment hash (for tracking)
    """
    from .invoices import validate_invoice_for_settlement, update_invoice_for_settlement
    
    logger.debug(f"Processing settlement for payment_hash={payment_hash}")
    
    # Track performance
    start_time = datetime.now()
    
    # Step 1: Validate the invoice for settlement
    valid, invoice, validation_message = await validate_invoice_for_settlement(payment_hash)
    
    # Special case: Already paid invoices are considered successful settlements
    if not valid and invoice is not None and validation_message == "Invoice already paid":
        logger.info(f"Invoice {payment_hash} already marked as paid, skipping settlement")
        return {
            "success": True,
            "message": "Invoice already paid",
            "invoice": invoice.dict() if invoice else None,
            "asset_id": invoice.asset_id if invoice else None,
            "asset_amount": invoice.asset_amount if invoice else None,
            "payment_hash": payment_hash,
            "status": "already_paid"
        }
    
    # Handle other validation failures
    if not valid:
        logger.warning(f"Settlement validation failed: {validation_message}")
        return {
            "success": False, 
            "error": validation_message,
            "payment_hash": payment_hash,
            "status": "validation_failed"
        }
    
    try:
        # Use our transaction context manager to ensure atomicity for all operations
        async with transaction() as conn:
            # Step 2: Update invoice status if requested
            updated_invoice = invoice
            if update_status and invoice:
                logger.debug(f"Updating invoice {invoice.id} status to 'paid'")
                updated_invoice = await update_invoice_for_settlement(invoice, conn)
                if not updated_invoice:
                    logger.error(f"Failed to update invoice status for {invoice.id}")
                    return {
                        "success": False,
                        "error": "Failed to update invoice status",
                        "payment_hash": payment_hash,
                        "status": "update_failed"
                    }
            
            # Step 3: Record the asset transaction
            if updated_invoice:
                tx_success, tx, tx_error = await record_settlement_transaction(
                    invoice=updated_invoice,
                    payment_hash=payment_hash,
                    conn=conn
                )
                
                # Handle transaction recording failure
                if not tx_success:
                    logger.warning(f"Invoice paid but transaction recording failed: {tx_error}")
                    return {
                        "success": True,
                        "partial": True,
                        "message": "Invoice marked as paid but failed to record transaction",
                        "invoice": updated_invoice.dict() if updated_invoice else None,
                        "asset_id": updated_invoice.asset_id if updated_invoice else None,
                        "asset_amount": updated_invoice.asset_amount if updated_invoice else None,
                        "payment_hash": payment_hash,
                        "warning": tx_error,
                        "status": "paid_tx_failed"
                    }
                
                # Step 4: All steps successful
                processing_time = (datetime.now() - start_time).total_seconds()
                logger.info(f"Settlement completed successfully for invoice {updated_invoice.id} in {processing_time:.2f}s")
                
                return {
                    "success": True, 
                    "message": "Settlement processed successfully",
                    "invoice": updated_invoice.dict() if updated_invoice else None,
                    "asset_id": updated_invoice.asset_id if updated_invoice else None,
                    "asset_amount": updated_invoice.asset_amount if updated_invoice else None,
                    "payment_hash": payment_hash,
                    "tx_id": tx.id if tx else None,
                    "status": "completed",
                    "processing_time": processing_time
                }
            else:
                # This should not happen, but handle it just in case
                logger.error(f"No valid invoice found for payment_hash={payment_hash}")
                return {
                    "success": False,
                    "error": "No valid invoice found",
                    "payment_hash": payment_hash,
                    "status": "error"
                }
            
    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"Settlement failed after {processing_time:.2f}s: {str(e)}")
        return {
            "success": False, 
            "error": str(e),
            "payment_hash": payment_hash,
            "status": "error",
            "processing_time": processing_time
        }
