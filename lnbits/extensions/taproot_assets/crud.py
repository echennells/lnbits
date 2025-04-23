"""
Database module for the Taproot Assets extension.
"""
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from loguru import logger

from lnbits.db import Connection, Database
from lnbits.helpers import urlsafe_short_hash

from .models import (
    TaprootSettings, TaprootAsset, TaprootInvoice,
    FeeTransaction, TaprootPayment, AssetBalance, AssetTransaction
)

# Create a database instance for the extension
db = Database("ext_taproot_assets")


#
# Settings
#

async def get_or_create_settings() -> TaprootSettings:
    """Get or create Taproot Assets extension settings."""
    async with db.connect() as conn:
        row = await conn.fetchone("SELECT * FROM settings LIMIT 1")
        if row:
            return TaprootSettings(**dict(row))

        # Create default settings
        settings = TaprootSettings()
        settings_id = urlsafe_short_hash()
        await conn.execute(
            """
            INSERT INTO settings (
                id, tapd_host, tapd_network, tapd_tls_cert_path,
                tapd_macaroon_path, tapd_macaroon_hex,
                lnd_macaroon_path, lnd_macaroon_hex, default_sat_fee
            )
            VALUES (:id, :tapd_host, :tapd_network, :tapd_tls_cert_path,
                    :tapd_macaroon_path, :tapd_macaroon_hex,
                    :lnd_macaroon_path, :lnd_macaroon_hex, :default_sat_fee)
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
            },
        )
        return settings


async def update_settings(settings: TaprootSettings) -> TaprootSettings:
    """Update Taproot Assets extension settings."""
    async with db.connect() as conn:
        # Get existing settings ID or create a new one
        row = await conn.fetchone("SELECT id FROM settings LIMIT 1")
        settings_id = row["id"] if row else urlsafe_short_hash()

        await conn.execute(
            """
            INSERT OR REPLACE INTO settings (
                id, tapd_host, tapd_network, tapd_tls_cert_path,
                tapd_macaroon_path, tapd_macaroon_hex,
                lnd_macaroon_path, lnd_macaroon_hex, default_sat_fee
            )
            VALUES (:id, :tapd_host, :tapd_network, :tapd_tls_cert_path,
                    :tapd_macaroon_path, :tapd_macaroon_hex,
                    :lnd_macaroon_path, :lnd_macaroon_hex, :default_sat_fee)
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
            },
        )
        return settings


#
# Assets
#

async def create_asset(asset_data: Dict[str, Any], user_id: str) -> TaprootAsset:
    """Create a new Taproot Asset record."""
    async with db.connect() as conn:
        asset_id = urlsafe_short_hash()
        now = datetime.now()

        # Convert channel_info to JSON string if present
        channel_info_json = json.dumps(asset_data.get("channel_info")) if asset_data.get("channel_info") else None

        await conn.execute(
            """
            INSERT INTO assets (
                id, name, asset_id, type, amount, genesis_point, meta_hash,
                version, is_spent, script_key, channel_info, user_id,
                created_at, updated_at
            )
            VALUES (
                :id, :name, :asset_id, :type, :amount, :genesis_point, :meta_hash,
                :version, :is_spent, :script_key, :channel_info, :user_id,
                :created_at, :updated_at
            )
            """,
            {
                "id": asset_id,
                "name": asset_data.get("name", "Unknown"),
                "asset_id": asset_data["asset_id"],
                "type": asset_data["type"],
                "amount": asset_data["amount"],
                "genesis_point": asset_data["genesis_point"],
                "meta_hash": asset_data["meta_hash"],
                "version": asset_data["version"],
                "is_spent": asset_data["is_spent"],
                "script_key": asset_data["script_key"],
                "channel_info": channel_info_json,
                "user_id": user_id,
                "created_at": now,
                "updated_at": now,
            },
        )

        return TaprootAsset(
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


async def get_assets(user_id: str) -> List[TaprootAsset]:
    """Get all Taproot Assets for a user."""
    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM assets WHERE user_id = :user_id ORDER BY created_at DESC",
            {"user_id": user_id},
        )

        assets = []
        for row in rows:
            # Parse channel_info JSON if present
            channel_info = json.loads(row["channel_info"]) if row["channel_info"] else None

            asset = TaprootAsset(
                id=row["id"],
                name=row["name"],
                asset_id=row["asset_id"],
                type=row["type"],
                amount=row["amount"],
                genesis_point=row["genesis_point"],
                meta_hash=row["meta_hash"],
                version=row["version"],
                is_spent=row["is_spent"],
                script_key=row["script_key"],
                channel_info=channel_info,
                user_id=row["user_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            assets.append(asset)

        return assets


async def get_asset(asset_id: str) -> Optional[TaprootAsset]:
    """Get a specific Taproot Asset by ID."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM assets WHERE id = :id",
            {"id": asset_id},
        )

        if not row:
            return None

        # Parse channel_info JSON if present
        channel_info = json.loads(row["channel_info"]) if row["channel_info"] else None

        return TaprootAsset(
            id=row["id"],
            name=row["name"],
            asset_id=row["asset_id"],
            type=row["type"],
            amount=row["amount"],
            genesis_point=row["genesis_point"],
            meta_hash=row["meta_hash"],
            version=row["version"],
            is_spent=row["is_spent"],
            script_key=row["script_key"],
            channel_info=channel_info,
            user_id=row["user_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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
    async with db.connect() as conn:
        invoice_id = urlsafe_short_hash()
        now = datetime.now()
        expires_at = now + timedelta(seconds=expiry) if expiry else None

        params = {
            "id": invoice_id,
            "payment_hash": payment_hash,
            "payment_request": payment_request,
            "asset_id": asset_id,
            "asset_amount": asset_amount,
            "satoshi_amount": satoshi_amount,
            "memo": memo,
            "status": "pending",
            "user_id": user_id,
            "wallet_id": wallet_id,
            "created_at": now,
            "expires_at": expires_at,
        }

        await conn.execute(
            """
            INSERT INTO invoices (
                id, payment_hash, payment_request, asset_id, asset_amount,
                satoshi_amount, memo, status, user_id, wallet_id,
                created_at, expires_at
            )
            VALUES (
                :id, :payment_hash, :payment_request, :asset_id, :asset_amount,
                :satoshi_amount, :memo, :status, :user_id, :wallet_id,
                :created_at, :expires_at
            )
            """,
            params
        )

        return TaprootInvoice(
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


async def get_invoice(invoice_id: str) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by ID."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM invoices WHERE id = :id",
            {"id": invoice_id},
        )

        if not row:
            return None

        return TaprootInvoice(
            id=row["id"],
            payment_hash=row["payment_hash"],
            payment_request=row["payment_request"],
            asset_id=row["asset_id"],
            asset_amount=row["asset_amount"],
            satoshi_amount=row["satoshi_amount"],
            memo=row["memo"],
            status=row["status"],
            user_id=row["user_id"],
            wallet_id=row["wallet_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            paid_at=row["paid_at"],
        )


async def get_invoice_by_payment_hash(payment_hash: str) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by payment hash."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM invoices WHERE payment_hash = :payment_hash",
            {"payment_hash": payment_hash},
        )

        if not row:
            return None

        return TaprootInvoice(
            id=row["id"],
            payment_hash=row["payment_hash"],
            payment_request=row["payment_request"],
            asset_id=row["asset_id"],
            asset_amount=row["asset_amount"],
            satoshi_amount=row["satoshi_amount"],
            memo=row["memo"],
            status=row["status"],
            user_id=row["user_id"],
            wallet_id=row["wallet_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            paid_at=row["paid_at"],
        )


async def update_invoice_status(invoice_id: str, status: str) -> Optional[TaprootInvoice]:
    """Update the status of a Taproot Asset invoice."""
    async with db.connect() as conn:
        now = datetime.now()
        paid_at = now if status == "paid" else None

        # Update the invoice status
        await conn.execute(
            """
            UPDATE invoices
            SET status = :status, paid_at = :paid_at
            WHERE id = :id
            """,
            {
                "status": status,
                "paid_at": paid_at,
                "id": invoice_id
            },
        )

        # Fetch the updated invoice
        row = await conn.fetchone(
            "SELECT * FROM invoices WHERE id = :id",
            {"id": invoice_id},
        )

        if not row:
            return None

        return TaprootInvoice(
            id=row["id"],
            payment_hash=row["payment_hash"],
            payment_request=row["payment_request"],
            asset_id=row["asset_id"],
            asset_amount=row["asset_amount"],
            satoshi_amount=row["satoshi_amount"],
            memo=row["memo"],
            status=row["status"],
            user_id=row["user_id"],
            wallet_id=row["wallet_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            paid_at=row["paid_at"],
        )


async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
    """Get all Taproot Asset invoices for a user."""
    try:
        async with db.connect() as conn:
            rows = await conn.fetchall(
                "SELECT * FROM invoices WHERE user_id = :user_id ORDER BY created_at DESC",
                {"user_id": user_id},
            )

            invoices = []
            for row in rows:
                invoice = TaprootInvoice(
                    id=row["id"],
                    payment_hash=row["payment_hash"],
                    payment_request=row["payment_request"],
                    asset_id=row["asset_id"],
                    asset_amount=row["asset_amount"],
                    satoshi_amount=row["satoshi_amount"],
                    memo=row["memo"],
                    status=row["status"],
                    user_id=row["user_id"],
                    wallet_id=row["wallet_id"],
                    created_at=row["created_at"],
                    expires_at=row["expires_at"],
                    paid_at=row["paid_at"],
                )
                invoices.append(invoice)

            return invoices
    except Exception as e:
        logger.error(f"Error in get_user_invoices: {str(e)}")
        raise


# New function for self-payment detection (original - kept for backward compatibility)
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


# New function for internal payment detection
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
    async with db.connect() as conn:
        transaction_id = urlsafe_short_hash()
        now = datetime.now()

        await conn.execute(
            """
            INSERT INTO fee_transactions (
                id, user_id, wallet_id, asset_payment_hash, fee_amount_msat, status, created_at
            )
            VALUES (
                :id, :user_id, :wallet_id, :asset_payment_hash, :fee_amount_msat, :status, :created_at
            )
            """,
            {
                "id": transaction_id,
                "user_id": user_id,
                "wallet_id": wallet_id,
                "asset_payment_hash": asset_payment_hash,
                "fee_amount_msat": fee_amount_msat,
                "status": status,
                "created_at": now
            },
        )

        return FeeTransaction(
            id=transaction_id,
            user_id=user_id,
            wallet_id=wallet_id,
            asset_payment_hash=asset_payment_hash,
            fee_amount_msat=fee_amount_msat,
            status=status,
            created_at=now
        )


async def get_fee_transactions(user_id: Optional[str] = None) -> List[FeeTransaction]:
    """Get fee transactions, optionally filtered by user ID."""
    async with db.connect() as conn:
        if user_id:
            rows = await conn.fetchall(
                "SELECT * FROM fee_transactions WHERE user_id = :user_id ORDER BY created_at DESC",
                {"user_id": user_id},
            )
        else:
            rows = await conn.fetchall(
                "SELECT * FROM fee_transactions ORDER BY created_at DESC"
            )

        transactions = []
        for row in rows:
            transaction = FeeTransaction(
                id=row["id"],
                user_id=row["user_id"],
                wallet_id=row["wallet_id"],
                asset_payment_hash=row["asset_payment_hash"],
                fee_amount_msat=row["fee_amount_msat"],
                status=row["status"],
                created_at=row["created_at"]
            )
            transactions.append(transaction)

        return transactions


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
    async with db.connect() as conn:
        payment_id = urlsafe_short_hash()
        now = datetime.now()
        
        await conn.execute(
            """
            INSERT INTO payments (
                id, payment_hash, payment_request, asset_id, asset_amount, fee_sats, 
                memo, status, user_id, wallet_id, created_at, preimage
            )
            VALUES (
                :id, :payment_hash, :payment_request, :asset_id, :asset_amount, :fee_sats, 
                :memo, :status, :user_id, :wallet_id, :created_at, :preimage
            )
            """,
            {
                "id": payment_id,
                "payment_hash": payment_hash, 
                "payment_request": payment_request,
                "asset_id": asset_id, 
                "asset_amount": asset_amount,
                "fee_sats": fee_sats,
                "memo": memo,
                "status": "completed",
                "user_id": user_id,
                "wallet_id": wallet_id,
                "created_at": now,
                "preimage": preimage
            },
        )
        
        return TaprootPayment(
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


async def get_user_payments(user_id: str) -> List[TaprootPayment]:
    """Get all sent payments for a user."""
    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM payments WHERE user_id = :user_id ORDER BY created_at DESC",
            {"user_id": user_id},
        )
        
        payments = []
        for row in rows:
            payment = TaprootPayment(
                id=row["id"],
                payment_hash=row["payment_hash"],
                payment_request=row["payment_request"],
                asset_id=row["asset_id"], 
                asset_amount=row["asset_amount"],
                fee_sats=row["fee_sats"],
                memo=row["memo"],
                status=row["status"],
                user_id=row["user_id"],
                wallet_id=row["wallet_id"],
                created_at=row["created_at"],
                preimage=row["preimage"]
            )
            payments.append(payment)
            
        return payments


#
# Asset Balances
#

async def get_asset_balance(wallet_id: str, asset_id: str, conn: Optional[Connection] = None) -> Optional[AssetBalance]:
    """Get asset balance for a specific wallet and asset."""
    if conn:
        # Reuse existing connection
        row = await conn.fetchone(
            """
            SELECT * FROM asset_balances
            WHERE wallet_id = :wallet_id AND asset_id = :asset_id
            """,
            {
                "wallet_id": wallet_id,
                "asset_id": asset_id
            },
        )
    else:
        # Create new connection
        async with db.connect() as conn:
            row = await conn.fetchone(
                """
                SELECT * FROM asset_balances
                WHERE wallet_id = :wallet_id AND asset_id = :asset_id
                """,
                {
                    "wallet_id": wallet_id,
                    "asset_id": asset_id
                },
            )

    if not row:
        return None

    return AssetBalance(
        id=row["id"],
        wallet_id=row["wallet_id"],
        asset_id=row["asset_id"],
        balance=row["balance"],
        last_payment_hash=row["last_payment_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )


async def get_wallet_asset_balances(wallet_id: str) -> List[AssetBalance]:
    """Get all asset balances for a wallet."""
    async with db.connect() as conn:
        rows = await conn.fetchall(
            """
            SELECT * FROM asset_balances
            WHERE wallet_id = :wallet_id
            ORDER BY updated_at DESC
            """,
            {"wallet_id": wallet_id},
        )

        balances = []
        for row in rows:
            balance = AssetBalance(
                id=row["id"],
                wallet_id=row["wallet_id"],
                asset_id=row["asset_id"],
                balance=row["balance"],
                last_payment_hash=row["last_payment_hash"],
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )
            balances.append(balance)

        return balances


async def update_asset_balance(
    wallet_id: str,
    asset_id: str,
    amount_change: int,
    payment_hash: Optional[str] = None,
    conn: Optional[Connection] = None
) -> Optional[AssetBalance]:
    """Update asset balance, creating it if it doesn't exist."""
    now = datetime.now()
    
    if conn:
        # Reuse existing connection
        # Check if balance exists
        balance = await get_asset_balance(wallet_id, asset_id, conn)

        if balance:
            # Update existing balance
            await conn.execute(
                """
                UPDATE asset_balances
                SET balance = balance + :amount_change,
                    last_payment_hash = COALESCE(:payment_hash, last_payment_hash),
                    updated_at = :updated_at
                WHERE wallet_id = :wallet_id AND asset_id = :asset_id
                """,
                {
                    "amount_change": amount_change,
                    "payment_hash": payment_hash,
                    "updated_at": now,
                    "wallet_id": wallet_id,
                    "asset_id": asset_id
                },
            )
        else:
            # Create new balance
            balance_id = urlsafe_short_hash()
            await conn.execute(
                """
                INSERT INTO asset_balances (
                    id, wallet_id, asset_id, balance, last_payment_hash, created_at, updated_at
                )
                VALUES (
                    :id, :wallet_id, :asset_id, :balance, :last_payment_hash, :created_at, :updated_at
                )
                """,
                {
                    "id": balance_id,
                    "wallet_id": wallet_id,
                    "asset_id": asset_id,
                    "balance": amount_change,
                    "last_payment_hash": payment_hash,
                    "created_at": now,
                    "updated_at": now
                },
            )
        
        # Return the updated balance
        return await get_asset_balance(wallet_id, asset_id, conn)
    else:
        # Create new connection
        async with db.connect() as conn:
            # Begin transaction explicitly
            await conn.execute("BEGIN TRANSACTION")
            try:
                result = await update_asset_balance(wallet_id, asset_id, amount_change, payment_hash, conn)
                await conn.execute("COMMIT")
                return result
            except Exception as e:
                await conn.execute("ROLLBACK")
                logger.error(f"Failed to update asset balance: {str(e)}")
                raise


async def record_asset_transaction(
    wallet_id: str,
    asset_id: str,
    amount: int,
    tx_type: str,  # 'credit' or 'debit'
    payment_hash: Optional[str] = None,
    fee: int = 0,
    memo: Optional[str] = None,
    conn: Optional[Connection] = None
) -> AssetTransaction:
    """Record an asset transaction and update the balance."""
    if conn:
        # Reuse existing connection
        tx_id = urlsafe_short_hash()
        now = datetime.now()

        # Insert transaction record
        await conn.execute(
            """
            INSERT INTO asset_transactions (
                id, wallet_id, asset_id, payment_hash, amount, fee, memo, type, created_at
            )
            VALUES (
                :id, :wallet_id, :asset_id, :payment_hash, :amount, :fee, :memo, :type, :created_at
            )
            """,
            {
                "id": tx_id,
                "wallet_id": wallet_id,
                "asset_id": asset_id,
                "payment_hash": payment_hash,
                "amount": amount,
                "fee": fee,
                "memo": memo,
                "type": tx_type,
                "created_at": now
            },
        )

        # Update balance
        # For debit, amount should be negative for balance update
        balance_change = amount if tx_type == 'credit' else -amount
        await update_asset_balance(wallet_id, asset_id, balance_change, payment_hash, conn)

        return AssetTransaction(
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
    else:
        # Create new connection
        async with db.connect() as conn:
            # Begin transaction explicitly to ensure atomicity
            await conn.execute("BEGIN TRANSACTION")
            try:
                result = await record_asset_transaction(
                    wallet_id, asset_id, amount, tx_type, payment_hash, fee, memo, conn
                )
                await conn.execute("COMMIT")
                return result
            except Exception as e:
                # Rollback on error
                await conn.execute("ROLLBACK")
                logger.error(f"Transaction failed, rolling back: {str(e)}")
                raise


async def get_asset_transactions(
    wallet_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    limit: int = 100
) -> List[AssetTransaction]:
    """Get asset transactions, optionally filtered by wallet and/or asset."""
    async with db.connect() as conn:
        # Build query
        query = "SELECT * FROM asset_transactions"
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

        # Execute query
        rows = await conn.fetchall(query, params)

        transactions = []
        for row in rows:
            tx = AssetTransaction(
                id=row["id"],
                wallet_id=row["wallet_id"],
                asset_id=row["asset_id"],
                payment_hash=row["payment_hash"],
                amount=row["amount"],
                fee=row["fee"],
                memo=row["memo"],
                type=row["type"],
                created_at=row["created_at"]
            )
            transactions.append(tx)

        return transactions
