"""
Database module for the Taproot Assets extension.
"""
import json
import uuid
import traceback
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from loguru import logger

from lnbits.db import Connection, Database
from lnbits.helpers import urlsafe_short_hash

from .models import (
    TaprootSettings, TaprootAsset, TaprootInvoice,
    FeeTransaction, TaprootPayment, AssetBalance, AssetTransaction
)

# Create a database instance for the extension
db = Database("ext_taproot_assets")

# Determine schema prefix to use based on database type
SCHEMA_PREFIX = "taproot_assets."

#
# Settings
#

async def get_or_create_settings() -> TaprootSettings:
    """Get or create Taproot Assets extension settings."""
    row = await db.fetchone(
        f"SELECT * FROM {SCHEMA_PREFIX}settings LIMIT 1", 
        {}, 
        TaprootSettings
    )
    if row:
        return row

    # Create default settings
    settings = TaprootSettings()
    settings_id = urlsafe_short_hash()
    
    # Insert using direct SQL without setting the ID on the model
    await db.execute(
        f"""
        INSERT INTO {SCHEMA_PREFIX}settings (
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
            "tapd_host": settings.tapd_host,
            "tapd_network": settings.tapd_network,
            "tapd_tls_cert_path": settings.tapd_tls_cert_path,
            "tapd_macaroon_path": settings.tapd_macaroon_path,
            "tapd_macaroon_hex": settings.tapd_macaroon_hex,
            "lnd_macaroon_path": settings.lnd_macaroon_path,
            "lnd_macaroon_hex": settings.lnd_macaroon_hex,
            "default_sat_fee": settings.default_sat_fee,
        }
    )
    
    # Fetch the newly created settings
    return await db.fetchone(
        f"SELECT * FROM {SCHEMA_PREFIX}settings LIMIT 1", 
        {}, 
        TaprootSettings
    )


async def update_settings(settings: TaprootSettings) -> TaprootSettings:
    """Update Taproot Assets extension settings."""
    # Get existing settings ID or create a new one
    row = await db.fetchone(
        f"SELECT id FROM {SCHEMA_PREFIX}settings LIMIT 1",
        {},
        None
    )
    settings_id = row["id"] if row else urlsafe_short_hash()
    
    # If there's an existing row, update it using SQL directly
    if row:
        await db.execute(
            f"""
            UPDATE {SCHEMA_PREFIX}settings
            SET tapd_host = :tapd_host,
                tapd_network = :tapd_network,
                tapd_tls_cert_path = :tapd_tls_cert_path,
                tapd_macaroon_path = :tapd_macaroon_path,
                tapd_macaroon_hex = :tapd_macaroon_hex,
                lnd_macaroon_path = :lnd_macaroon_path,
                lnd_macaroon_hex = :lnd_macaroon_hex,
                default_sat_fee = :default_sat_fee
            WHERE id = :id
            """,
            {
                "id": settings_id,
                "tapd_host": settings.tapd_host,
                "tapd_network": settings.tapd_network,
                "tapd_tls_cert_path": settings.tapd_tls_cert_path,
                "tapd_macaroon_path": settings.tapd_macaroon_path,
                "tapd_macaroon_hex": settings.tapd_macaroon_hex,
                "lnd_macaroon_path": settings.lnd_macaroon_path,
                "lnd_macaroon_hex": settings.lnd_macaroon_hex,
                "default_sat_fee": settings.default_sat_fee,
            }
        )
    else:
        # Insert new record
        await db.execute(
            f"""
            INSERT INTO {SCHEMA_PREFIX}settings (
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
                "tapd_host": settings.tapd_host,
                "tapd_network": settings.tapd_network,
                "tapd_tls_cert_path": settings.tapd_tls_cert_path,
                "tapd_macaroon_path": settings.tapd_macaroon_path,
                "tapd_macaroon_hex": settings.tapd_macaroon_hex,
                "lnd_macaroon_path": settings.lnd_macaroon_path,
                "lnd_macaroon_hex": settings.lnd_macaroon_hex,
                "default_sat_fee": settings.default_sat_fee,
            }
        )
    
    # Return the updated settings
    return await db.fetchone(
        f"SELECT * FROM {SCHEMA_PREFIX}settings LIMIT 1", 
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

    # Convert channel_info to JSON string if present
    channel_info_json = json.dumps(asset_data.get("channel_info")) if asset_data.get("channel_info") else None
    
    # Create the asset model
    asset = TaprootAsset(
        id=asset_id,
        name=asset_data.get("name", "Unknown"),
        asset_id=asset_data["asset_id"],
        type=asset_data["type"],
        amount=asset_data["amount"],
        genesis_point=asset_data["genesis_point"],
        meta_hash=asset_data["meta_hash"],
        version=asset_data["version"],
        is_spent=asset_data["is_spent"],
        script_key=asset_data["script_key"],
        channel_info=asset_data.get("channel_info"),
        user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    
    # Insert the asset using standard pattern
    await db.insert(f"{SCHEMA_PREFIX}assets", asset)
    
    return asset


async def get_assets(user_id: str) -> List[TaprootAsset]:
    """Get all Taproot Assets for a user."""
    return await db.fetchall(
        f"SELECT * FROM {SCHEMA_PREFIX}assets WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id},
        TaprootAsset
    )


async def get_asset(asset_id: str) -> Optional[TaprootAsset]:
    """Get a specific Taproot Asset by ID."""
    return await db.fetchone(
        f"SELECT * FROM {SCHEMA_PREFIX}assets WHERE id = :id",
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
) -> TaprootInvoice:
    """Create a new Taproot Asset invoice."""
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
    )
    
    # Insert using standard pattern
    await db.insert(f"{SCHEMA_PREFIX}invoices", invoice)
    
    return invoice


async def get_invoice(invoice_id: str) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by ID."""
    return await db.fetchone(
        f"SELECT * FROM {SCHEMA_PREFIX}invoices WHERE id = :id",
        {"id": invoice_id},
        TaprootInvoice
    )


async def get_invoice_by_payment_hash(payment_hash: str) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by payment hash."""
    return await db.fetchone(
        f"SELECT * FROM {SCHEMA_PREFIX}invoices WHERE payment_hash = :payment_hash",
        {"payment_hash": payment_hash},
        TaprootInvoice
    )


async def update_invoice_status(invoice_id: str, status: str) -> Optional[TaprootInvoice]:
    """Update the status of a Taproot Asset invoice."""
    invoice = await get_invoice(invoice_id)
    if not invoice:
        return None
        
    now = datetime.now()
    invoice.status = status
    
    # Set paid_at timestamp if status is changing to paid
    if status == "paid":
        invoice.paid_at = now
    
    # Update the invoice in the database
    await db.update(
        f"{SCHEMA_PREFIX}invoices",
        invoice,
        "WHERE id = :id"
    )
    
    # Return the updated invoice
    return await get_invoice(invoice_id)


async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
    """Get all Taproot Asset invoices for a user."""
    return await db.fetchall(
        f"SELECT * FROM {SCHEMA_PREFIX}invoices WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id},
        TaprootInvoice
    )


# Payment detection functions
async def is_self_payment(payment_hash: str, user_id: str) -> bool:
    """
    Determine if a payment hash belongs to an invoice created by the same user.
    
    Args:
        payment_hash: The payment hash to check
        user_id: The ID of the current user
        
    Returns:
        bool: True if this is a self-payment, False otherwise
    """
    invoice = await get_invoice_by_payment_hash(payment_hash)
    return invoice is not None and invoice.user_id == user_id


async def is_internal_payment(payment_hash: str) -> bool:
    """
    Determine if a payment hash belongs to an invoice created by any user on the same node.
    This identifies payments between any users on the same LNbits instance.
    
    Args:
        payment_hash: The payment hash to check
        
    Returns:
        bool: True if this is an internal payment, False otherwise
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
    
    # Insert the transaction
    await db.insert(f"{SCHEMA_PREFIX}fee_transactions", fee_transaction)
    
    return fee_transaction


async def get_fee_transactions(user_id: Optional[str] = None) -> List[FeeTransaction]:
    """Get fee transactions, optionally filtered by user ID."""
    if user_id:
        return await db.fetchall(
            f"SELECT * FROM {SCHEMA_PREFIX}fee_transactions WHERE user_id = :user_id ORDER BY created_at DESC",
            {"user_id": user_id},
            FeeTransaction
        )
    else:
        return await db.fetchall(
            f"SELECT * FROM {SCHEMA_PREFIX}fee_transactions ORDER BY created_at DESC",
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
    
    # Insert using standard pattern
    await db.insert(f"{SCHEMA_PREFIX}payments", payment)
    
    return payment


async def get_user_payments(user_id: str) -> List[TaprootPayment]:
    """Get all sent payments for a user."""
    return await db.fetchall(
        f"SELECT * FROM {SCHEMA_PREFIX}payments WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id},
        TaprootPayment
    )


#
# Asset Balances
#

async def get_asset_balance(wallet_id: str, asset_id: str) -> Optional[AssetBalance]:
    """Get asset balance for a specific wallet and asset."""
    return await db.fetchone(
        f"""
        SELECT * FROM {SCHEMA_PREFIX}asset_balances
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
        SELECT * FROM {SCHEMA_PREFIX}asset_balances
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
    payment_hash: Optional[str] = None
) -> Optional[AssetBalance]:
    """Update asset balance, creating it if it doesn't exist."""
    now = datetime.now()
    
    # Check if balance exists
    balance = await get_asset_balance(wallet_id, asset_id)
    
    if balance:
        # Update existing balance
        balance.balance += amount_change
        if payment_hash:
            balance.last_payment_hash = payment_hash
        balance.updated_at = now
        
        # Update in database
        await db.update(
            f"{SCHEMA_PREFIX}asset_balances",
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
        
        # Insert new balance
        await db.insert(f"{SCHEMA_PREFIX}asset_balances", balance)
    
    # Return the updated balance
    return await get_asset_balance(wallet_id, asset_id)


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
    memo: Optional[str] = None
) -> AssetTransaction:
    """Record an asset transaction and update the balance."""
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
    
    # Insert transaction record
    await db.insert(f"{SCHEMA_PREFIX}asset_transactions", transaction)
    
    # Update balance
    # For debit, amount should be negative for balance update
    balance_change = amount if tx_type == 'credit' else -amount
    await update_asset_balance(wallet_id, asset_id, balance_change, payment_hash)
    
    return transaction


async def get_asset_transactions(
    wallet_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    limit: int = 100
) -> List[AssetTransaction]:
    """Get asset transactions, optionally filtered by wallet and/or asset."""
    # Build query
    query = f"SELECT * FROM {SCHEMA_PREFIX}asset_transactions"
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


async def process_settlement_transaction(
    payment_hash: str,
    user_id: str,
    wallet_id: str,
    update_status: bool = True,
    notify_websocket: bool = True
) -> Dict[str, Any]:
    """
    Process a settlement transaction using LNbits standard patterns.
    
    Args:
        payment_hash: The payment hash of the invoice to settle
        user_id: User ID for the invoice owner
        wallet_id: Wallet ID for the invoice owner
        update_status: Whether to update the invoice status
        notify_websocket: Whether to send WebSocket notifications
        
    Returns:
        Dict with settlement results
    """
    # Get the invoice
    invoice = await get_invoice_by_payment_hash(payment_hash)
    if not invoice:
        return {"success": False, "error": "Invoice not found"}
        
    # Check if already paid
    if invoice.status == "paid":
        return {"success": True, "message": "Invoice already paid", "invoice": invoice.dict()}
    
    try:
        # Update invoice status if needed
        if update_status:
            invoice.status = "paid"
            invoice.paid_at = datetime.now()
            await db.update(
                f"{SCHEMA_PREFIX}invoices", 
                invoice,
                "WHERE id = :id"
            )
        
        # Create asset transaction for credit
        memo = invoice.memo or f"Received {invoice.asset_amount} of asset {invoice.asset_id}"
        await record_asset_transaction(
            wallet_id=invoice.wallet_id,
            asset_id=invoice.asset_id,
            amount=invoice.asset_amount,
            tx_type="credit",  # This is an incoming payment
            payment_hash=payment_hash,
            memo=memo
        )
        
        # Return success response
        return {
            "success": True, 
            "message": "Settlement processed successfully",
            "invoice": invoice.dict(),
            "asset_id": invoice.asset_id,
            "asset_amount": invoice.asset_amount
        }
            
    except Exception as e:
        logger.error(f"Error in settlement: {str(e)}")
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}
