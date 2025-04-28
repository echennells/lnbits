"""
Database module for the Taproot Assets extension.
"""
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple, Union, Literal
from loguru import logger

from lnbits.helpers import urlsafe_short_hash

from .models import (
    TaprootSettings, TaprootAsset, TaprootInvoice,
    FeeTransaction, TaprootPayment, AssetBalance, AssetTransaction
)

# Create a database instance for the extension
from lnbits.db import Database
from .db import db, get_table_name


#
# Settings
#

async def get_or_create_settings() -> TaprootSettings:
    """Get or create Taproot Assets extension settings."""
    row = await db.fetchone(
        f"SELECT * FROM {get_table_name('settings')} LIMIT 1", 
        {}, 
        TaprootSettings
    )
    if row:
        return row

    # Create default settings with ID included
    settings_id = urlsafe_short_hash()
    
    # Insert using direct SQL to avoid the model issue
    await db.execute(
        f"""
        INSERT INTO {get_table_name('settings')} (
            id, tapd_host, tapd_network, tapd_tls_cert_path,
            tapd_macaroon_path, tapd_macaroon_hex,
            lnd_macaroon_path, lnd_macaroon_hex, default_sat_fee
        )
        VALUES (
            :id, :tapd_host, :tapd_network, :tapd_tls_cert_path,
            :tapd_macaroon_path, :tapd_macaroon_hex,
            :lnd_macaroon_path, :lnd_macaroon_hex, :default_sat_fee
        )
        """,
        {
            "id": settings_id,
            "tapd_host": "lit:10009",
            "tapd_network": "mainnet",
            "tapd_tls_cert_path": "/root/.lnd/tls.cert",
            "tapd_macaroon_path": "/root/.tapd/data/mainnet/admin.macaroon",
            "tapd_macaroon_hex": None,
            "lnd_macaroon_path": "/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
            "lnd_macaroon_hex": None,
            "default_sat_fee": 1,
        }
    )
    
    # Fetch the newly created settings
    return await db.fetchone(
        f"SELECT * FROM {get_table_name('settings')} LIMIT 1", 
        {}, 
        TaprootSettings
    )


async def update_settings(settings: TaprootSettings) -> TaprootSettings:
    """Update Taproot Assets extension settings."""
    # Get existing settings ID or create a new one
    row = await db.fetchone(
        f"SELECT id FROM {get_table_name('settings')} LIMIT 1",
        {},
        None
    )
    
    if row:
        # Update existing settings
        # Set the ID from the existing record
        settings.id = row["id"]
        await db.update(
            get_table_name("settings"),
            settings,
            "WHERE id = :id"
        )
    else:
        # Create new settings with a generated ID
        settings.id = urlsafe_short_hash()
        await db.insert(get_table_name("settings"), settings)
    
    # Return the updated settings
    return await db.fetchone(
        f"SELECT * FROM {get_table_name('settings')} LIMIT 1", 
        {}, 
        TaprootSettings
    )


#
# Assets
#

async def create_asset(asset_data: Dict[str, Any], user_id: str) -> TaprootAsset:
    """Create a new Taproot Asset record."""
    asset_id = urlsafe_short_hash()
    now = datetime.now()

    # Create the asset model with more concise initialization
    asset_dict = {
        "id": asset_id,
        "name": asset_data.get("name", "Unknown"),
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
        # Properly handle channel_info which might need to be JSON serialized
        "channel_info": asset_data.get("channel_info"),
    }
    
    # Add all the required fields from asset_data
    for field in ["asset_id", "type", "amount", "genesis_point", 
                 "meta_hash", "version", "is_spent", "script_key"]:
        asset_dict[field] = asset_data[field]
    
    # Create the asset model
    asset = TaprootAsset(**asset_dict)
    
    # Insert using standard pattern
    await db.insert(get_table_name("assets"), asset)
    
    return asset


async def get_assets(user_id: str, conn=None) -> List[TaprootAsset]:
    """
    Get all Taproot Assets for a user.
    
    Args:
        user_id: The user ID to get assets for
        conn: Optional database connection to reuse
        
    Returns:
        List[TaprootAsset]: List of assets owned by the user
    """
    return await (conn or db).fetchall(
        f"SELECT * FROM {get_table_name('assets')} WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id},
        TaprootAsset
    )


async def get_asset(asset_id: str, conn=None) -> Optional[TaprootAsset]:
    """
    Get a specific Taproot Asset by ID.
    
    Args:
        asset_id: The asset ID to look up
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootAsset]: The asset if found, None otherwise
    """
    return await (conn or db).fetchone(
        f"SELECT * FROM {get_table_name('assets')} WHERE id = :id",
        {"id": asset_id},
        TaprootAsset
    )


#
# Invoices
#

async def create_invoice(
    asset_id: str,
    asset_amount: int,
    satoshi_amount: int,
    payment_hash: str,
    payment_request: str,
    user_id: str,
    wallet_id: str,
    memo: Optional[str] = None,
    expiry: Optional[int] = None,
    conn=None
) -> TaprootInvoice:
    """
    Create a new Taproot Asset invoice.
    
    Args:
        asset_id: The ID of the asset being invoiced
        asset_amount: The amount of the asset being invoiced
        satoshi_amount: The satoshi amount for protocol requirements
        payment_hash: The payment hash for the invoice
        payment_request: The payment request string
        user_id: The ID of the user creating the invoice
        wallet_id: The ID of the wallet for the invoice
        memo: Optional memo for the invoice
        expiry: Optional expiry time in seconds
        conn: Optional database connection to reuse
        
    Returns:
        TaprootInvoice: The created invoice
    """
    invoice_id = urlsafe_short_hash()
    now = datetime.now()
    expires_at = now + timedelta(seconds=expiry) if expiry else None

    # Create invoice model
    invoice = TaprootInvoice(
        id=invoice_id,
        payment_hash=payment_hash,
        payment_request=payment_request,
        asset_id=asset_id,
        asset_amount=asset_amount,
        satoshi_amount=satoshi_amount,
        memo=memo,
        status="pending",
        user_id=user_id,
        wallet_id=wallet_id,
        created_at=now,
        expires_at=expires_at,
        paid_at=None
    )
    
    # Insert using standardized method
    await (conn or db).insert(get_table_name("invoices"), invoice)
    
    return invoice


async def get_invoice(invoice_id: str, conn=None) -> Optional[TaprootInvoice]:
    """
    Get a specific Taproot Asset invoice by ID.
    
    Args:
        invoice_id: The ID of the invoice to get
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The invoice if found, None otherwise
    """
    return await (conn or db).fetchone(
        f"SELECT * FROM {get_table_name('invoices')} WHERE id = :id",
        {"id": invoice_id},
        TaprootInvoice
    )


async def get_invoice_by_payment_hash(payment_hash: str, conn=None) -> Optional[TaprootInvoice]:
    """
    Get a specific Taproot Asset invoice by payment hash.
    
    Args:
        payment_hash: The payment hash to look up
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The invoice if found, None otherwise
    """
    return await (conn or db).fetchone(
        f"SELECT * FROM {get_table_name('invoices')} WHERE payment_hash = :payment_hash",
        {"payment_hash": payment_hash},
        TaprootInvoice
    )


async def update_invoice_status(invoice_id: str, status: str, conn=None) -> Optional[TaprootInvoice]:
    """
    Update the status of a Taproot Asset invoice.
    
    Args:
        invoice_id: The ID of the invoice to update
        status: The new status for the invoice
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The updated invoice if found, None otherwise
    """
    invoice = await get_invoice(invoice_id, conn)
    if not invoice:
        return None
        
    now = datetime.now()
    invoice.status = status
    
    # Set paid_at timestamp if status is changing to paid
    if status == "paid":
        invoice.paid_at = now
    
    # Update the invoice in the database using standardized method
    await (conn or db).update(
        get_table_name("invoices"),
        invoice,
        "WHERE id = :id"
    )
    
    # Return the updated invoice
    return await get_invoice(invoice_id, conn)


async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
    """Get all Taproot Asset invoices for a user."""
    return await db.fetchall(
        f"SELECT * FROM {get_table_name('invoices')} WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id},
        TaprootInvoice
    )


# Payment detection functions
async def is_self_payment(payment_hash: str, user_id: str) -> bool:
    """
    Determine if a payment hash belongs to an invoice created by the same user.
    
    This function checks if the invoice associated with the payment hash was
    created by the user who is trying to pay it, which indicates a self-payment
    (user paying themselves).
    
    Args:
        payment_hash: The payment hash to check
        user_id: The ID of the current user
        
    Returns:
        bool: True if this is a self-payment (same user), False otherwise
    """
    invoice = await get_invoice_by_payment_hash(payment_hash)
    return invoice is not None and invoice.user_id == user_id


async def is_internal_payment(payment_hash: str) -> bool:
    """
    Determine if a payment hash belongs to an invoice created by any user on the same node.
    
    This function checks if the invoice associated with the payment hash exists in
    the local database, which means it was created by some user on this LNbits instance.
    This helps identify payments that can be processed internally without using the
    Lightning Network.
    
    Args:
        payment_hash: The payment hash to check
        
    Returns:
        bool: True if this is an internal payment (any user on same node), False otherwise
    """
    invoice = await get_invoice_by_payment_hash(payment_hash)
    return invoice is not None


#
# Fee Transactions
#

async def create_fee_transaction(
    user_id: str,
    wallet_id: str,
    asset_payment_hash: str,
    fee_amount_msat: int,
    status: str
) -> FeeTransaction:
    """Create a record of a satoshi fee transaction."""
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
    """Get fee transactions, optionally filtered by user ID."""
    if user_id:
        return await db.fetchall(
            f"SELECT * FROM {get_table_name('fee_transactions')} WHERE user_id = :user_id ORDER BY created_at DESC",
            {"user_id": user_id},
            FeeTransaction
        )
    else:
        return await db.fetchall(
            f"SELECT * FROM {get_table_name('fee_transactions')} ORDER BY created_at DESC",
            {},
            FeeTransaction
        )


#
# Payments
#

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
    """Create a record of a sent payment."""
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
    """Get all sent payments for a user."""
    return await db.fetchall(
        f"SELECT * FROM {get_table_name('payments')} WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id},
        TaprootPayment
    )


#
# Asset Balances
#

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
    """Get all asset balances for a wallet."""
    return await db.fetchall(
        f"""
        SELECT * FROM {get_table_name('asset_balances')}
        WHERE wallet_id = :wallet_id
        ORDER BY updated_at DESC
        """,
        {"wallet_id": wallet_id},
        AssetBalance
    )


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
        await (conn or db).update(
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
        await (conn or db).insert(get_table_name("asset_balances"), balance)
    
    # Return the updated balance
    return await get_asset_balance(wallet_id, asset_id, conn)


#
# Asset Transactions
#

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
    # Use a connection context manager to ensure atomicity
    async with db.reuse_conn(conn) if conn else db.connect() as new_conn:
        now = datetime.now()
        tx_id = urlsafe_short_hash()
        
        # Create transaction record
        transaction = AssetTransaction(
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
        await new_conn.insert(get_table_name("asset_transactions"), transaction)
        
        # Update balance
        # For debit, amount should be negative for balance update
        balance_change = amount if tx_type == 'credit' else -amount
        
        # Check if balance exists
        balance = await get_asset_balance(wallet_id, asset_id, conn=new_conn)
        
        if balance:
            # Update existing balance
            balance.balance += balance_change
            if payment_hash:
                balance.last_payment_hash = payment_hash
            balance.updated_at = now
            
            # Update in database using standardized method
            await new_conn.update(
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
            await new_conn.insert(get_table_name("asset_balances"), balance)
        
        return transaction


async def get_asset_transactions(
    wallet_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    limit: int = 100
) -> List[AssetTransaction]:
    """Get asset transactions, optionally filtered by wallet and/or asset."""
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


# Define types for settlement response
SettlementResponse = Dict[str, Any]

# Define helper functions for settlement process


async def validate_invoice_for_settlement(payment_hash: str, conn=None) -> Tuple[bool, Optional[TaprootInvoice], Optional[str]]:
    """
    Validate if an invoice can be settled.
    
    Args:
        payment_hash: The payment hash to check
        conn: Optional database connection to reuse
        
    Returns:
        Tuple containing:
        - success (bool): Whether the invoice is valid for settlement
        - invoice (Optional[TaprootInvoice]): The invoice if found
        - error_message (Optional[str]): Error message if validation fails
    """
    # Step 1: Check if invoice exists
    invoice = await get_invoice_by_payment_hash(payment_hash, conn)
    if not invoice:
        return False, None, "Invoice not found"
    
    # Step 2: Check if already paid
    if invoice.status == "paid":
        return False, invoice, "Invoice already paid"
    
    # Step 3: Check if expired
    now = datetime.now()
    if invoice.expires_at and invoice.expires_at < now:
        return False, invoice, "Invoice expired"
    
    # All validations passed
    return True, invoice, None


async def update_invoice_for_settlement(invoice: TaprootInvoice, conn=None) -> Optional[TaprootInvoice]:
    """
    Update an invoice to paid status for settlement.
    
    Args:
        invoice: The invoice to update
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The updated invoice or None if update failed
    """
    try:
        return await update_invoice_status(invoice.id, "paid", conn)
    except Exception as e:
        logger.error(f"Failed to update invoice status: {str(e)}")
        return None


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
        memo = invoice.memo or f"Received {invoice.asset_amount} of asset {invoice.asset_id}"
        
        transaction = await record_asset_transaction(
            wallet_id=invoice.wallet_id,
            asset_id=invoice.asset_id,
            amount=invoice.asset_amount,
            tx_type="credit",
            payment_hash=payment_hash,
            memo=memo,
            conn=conn
        )
        
        return True, transaction, None
    except Exception as e:
        error_msg = f"Failed to record transaction: {str(e)}"
        logger.error(error_msg)
        return False, None, error_msg


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
        # Use a connection context manager to ensure atomicity for all operations
        async with db.connect() as conn:
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
                tx_success, transaction, tx_error = await record_settlement_transaction(
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
                    "tx_id": transaction.id if transaction else None,
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
