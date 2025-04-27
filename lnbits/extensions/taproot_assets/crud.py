"""
Database module for the Taproot Assets extension.
With direct transaction implementation to avoid nested transaction issues.
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

# Enable detailed debugging
DEBUG_TRANSACTIONS = True

# Helper function to debug transaction calls
def debug_tx(msg, method_name=None):
    if DEBUG_TRANSACTIONS:
        caller = traceback.extract_stack()[-2]
        line_no = caller.lineno
        file_name = caller.filename.split('/')[-1]
        method = method_name or caller.name
        logger.debug(f"[TX-DEBUG] {file_name}:{line_no} - {method}: {msg}")


#
# Settings
#

async def get_or_create_settings() -> TaprootSettings:
    """Get or create Taproot Assets extension settings."""
    row = await db.fetchone(
        "SELECT * FROM taproot_assets.settings LIMIT 1", 
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
        """
        INSERT INTO taproot_assets.settings (
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
        "SELECT * FROM taproot_assets.settings LIMIT 1", 
        {}, 
        TaprootSettings
    )


async def update_settings(settings: TaprootSettings) -> TaprootSettings:
    """Update Taproot Assets extension settings."""
    # Get existing settings ID or create a new one
    row = await db.fetchone(
        "SELECT id FROM taproot_assets.settings LIMIT 1",
        {},
        None
    )
    settings_id = row["id"] if row else urlsafe_short_hash()
    
    # If there's an existing row, update it using SQL directly
    if row:
        await db.execute(
            """
            UPDATE taproot_assets.settings
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
            """
            INSERT INTO taproot_assets.settings (
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
        "SELECT * FROM taproot_assets.settings LIMIT 1", 
        {}, 
        TaprootSettings
    )


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


async def get_invoice_by_payment_hash(payment_hash: str, conn: Optional[Connection] = None) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by payment hash."""
    debug_tx(f"START with payment_hash={payment_hash}, conn={conn is not None}")
    
    if conn:
        # Use existing connection
        debug_tx(f"Using provided connection")
        row = await conn.fetchone(
            "SELECT * FROM invoices WHERE payment_hash = :payment_hash",
            {"payment_hash": payment_hash},
        )
    else:
        # Create new connection
        debug_tx(f"Creating new connection")
        async with db.connect() as new_conn:
            row = await new_conn.fetchone(
                "SELECT * FROM invoices WHERE payment_hash = :payment_hash",
                {"payment_hash": payment_hash},
            )

    if not row:
        debug_tx(f"No invoice found")
        return None

    debug_tx(f"Invoice found, id={row['id']}, status={row['status']}")
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


async def update_invoice_status(invoice_id: str, status: str, conn: Optional[Connection] = None) -> Optional[TaprootInvoice]:
    """Update the status of a Taproot Asset invoice."""
    debug_tx(f"START with invoice_id={invoice_id}, status={status}, conn={conn is not None}")
    
    now = datetime.now()
    paid_at = now if status == "paid" else None

    if conn:
        # Use existing connection
        debug_tx(f"Using provided connection")
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
        debug_tx(f"Invoice status updated with conn")

        # Fetch the updated invoice
        row = await conn.fetchone(
            "SELECT * FROM invoices WHERE id = :id",
            {"id": invoice_id},
        )
        debug_tx(f"Invoice fetched after update with conn: {row is not None}")
    else:
        # Create new connection with transaction
        debug_tx(f"Creating new connection with transaction")
        async with db.connect() as new_conn:
            debug_tx(f"Beginning transaction in update_invoice_status")
            await new_conn.execute("BEGIN TRANSACTION")
            try:
                # Update the invoice status
                await new_conn.execute(
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
                debug_tx(f"Invoice status updated with new conn")

                # Fetch the updated invoice
                row = await new_conn.fetchone(
                    "SELECT * FROM invoices WHERE id = :id",
                    {"id": invoice_id},
                )
                debug_tx(f"Invoice fetched after update with new conn: {row is not None}")
                
                debug_tx(f"Committing transaction in update_invoice_status")
                await new_conn.execute("COMMIT")
            except Exception as e:
                debug_tx(f"Error in update_invoice_status, rolling back: {str(e)}")
                await new_conn.execute("ROLLBACK")
                logger.error(f"Failed to update invoice status: {str(e)}")
                raise

    if not row:
        debug_tx(f"No invoice found after update")
        return None

    debug_tx(f"Returning updated invoice")
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
    await db.insert("taproot_assets.fee_transactions", fee_transaction)
    
    return fee_transaction


async def get_fee_transactions(user_id: Optional[str] = None) -> List[FeeTransaction]:
    """Get fee transactions, optionally filtered by user ID."""
    if user_id:
        return await db.fetchall(
            "SELECT * FROM taproot_assets.fee_transactions WHERE user_id = :user_id ORDER BY created_at DESC",
            {"user_id": user_id},
            FeeTransaction
        )
    else:
        return await db.fetchall(
            "SELECT * FROM taproot_assets.fee_transactions ORDER BY created_at DESC",
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
    preimage: Optional[str] = None,
    conn: Optional[Connection] = None
) -> TaprootPayment:
    """Create a record of a sent payment."""
    debug_tx(f"START with payment_hash={payment_hash}, conn={conn is not None}")
    
    now = datetime.now()
    payment_id = urlsafe_short_hash()
    
    if conn:
        # Use existing connection
        debug_tx(f"Using provided connection")
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
        debug_tx(f"Payment record created with provided connection")
    else:
        # Create new connection with transaction
        debug_tx(f"Creating new connection with transaction")
        async with db.connect() as new_conn:
            debug_tx(f"Beginning transaction in create_payment_record")
            await new_conn.execute("BEGIN TRANSACTION")
            try:
                await new_conn.execute(
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
                debug_tx(f"Payment record created with new connection")
                debug_tx(f"Committing transaction in create_payment_record")
                await new_conn.execute("COMMIT")
            except Exception as e:
                debug_tx(f"Error in create_payment_record, rolling back: {str(e)}")
                await new_conn.execute("ROLLBACK")
                raise
        
    debug_tx(f"Returning payment record")
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
    debug_tx(f"START with wallet_id={wallet_id}, asset_id={asset_id}, conn={conn is not None}")
    
    if conn:
        # Reuse existing connection
        debug_tx(f"Using provided connection")
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
        debug_tx(f"Balance fetched with provided connection: {row is not None}")
    else:
        # Create new connection
        debug_tx(f"Creating new connection")
        async with db.connect() as new_conn:
            row = await new_conn.fetchone(
                """
                SELECT * FROM asset_balances
                WHERE wallet_id = :wallet_id AND asset_id = :asset_id
                """,
                {
                    "wallet_id": wallet_id,
                    "asset_id": asset_id
                },
            )
            debug_tx(f"Balance fetched with new connection: {row is not None}")

    if not row:
        debug_tx(f"No balance found")
        return None

    debug_tx(f"Returning balance: {row['balance']}")
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
    debug_tx(f"START with wallet_id={wallet_id}, asset_id={asset_id}, amount_change={amount_change}, conn={conn is not None}")
    
    now = datetime.now()
    
    if conn:
        # Reuse existing connection (no transaction management here)
        debug_tx(f"Using provided connection")
        # Check if balance exists
        balance = await get_asset_balance(wallet_id, asset_id, conn)
        debug_tx(f"Current balance: {balance.balance if balance else 'None'}")

        if balance:
            # Update existing balance
            debug_tx(f"Updating existing balance")
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
            debug_tx(f"Existing balance updated")
        else:
            # Create new balance
            debug_tx(f"Creating new balance")
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
            debug_tx(f"New balance created")
        
        # Return the updated balance
        debug_tx(f"Fetching updated balance")
        result = await get_asset_balance(wallet_id, asset_id, conn)
        debug_tx(f"Final balance: {result.balance if result else 'None'}")
        return result
    else:
        # Create new connection with transaction
        debug_tx(f"Creating new connection with transaction")
        async with db.connect() as new_conn:
            # Begin transaction explicitly
            debug_tx(f"Beginning transaction in update_asset_balance")
            await new_conn.execute("BEGIN TRANSACTION")
            try:
                # Check if balance exists
                balance = await get_asset_balance(wallet_id, asset_id, new_conn)
                debug_tx(f"Current balance: {balance.balance if balance else 'None'}")

                if balance:
                    # Update existing balance
                    debug_tx(f"Updating existing balance")
                    await new_conn.execute(
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
                    debug_tx(f"Existing balance updated")
                else:
                    # Create new balance
                    debug_tx(f"Creating new balance")
                    balance_id = urlsafe_short_hash()
                    await new_conn.execute(
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
                    debug_tx(f"New balance created")
                
                # Get the updated balance
                debug_tx(f"Fetching updated balance before commit")
                result = await get_asset_balance(wallet_id, asset_id, new_conn)
                debug_tx(f"Balance before commit: {result.balance if result else 'None'}")
                
                # Commit transaction
                debug_tx(f"Committing transaction in update_asset_balance")
                await new_conn.execute("COMMIT")
                debug_tx(f"Transaction committed")
                return result
            except Exception as e:
                # Rollback on error
                debug_tx(f"Error in update_asset_balance, rolling back: {str(e)}")
                await new_conn.execute("ROLLBACK")
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
    debug_tx(f"START with wallet_id={wallet_id}, asset_id={asset_id}, amount={amount}, tx_type={tx_type}, conn={conn is not None}")
    
    now = datetime.now()
    tx_id = urlsafe_short_hash()
    
    if conn:
        # Reuse existing connection (no transaction management here)
        debug_tx(f"Using provided connection")
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
        debug_tx(f"Transaction record created with ID {tx_id}")

        # Update balance
        # For debit, amount should be negative for balance update
        balance_change = amount if tx_type == 'credit' else -amount
        debug_tx(f"Updating balance with amount_change={balance_change}")
        await update_asset_balance(wallet_id, asset_id, balance_change, payment_hash, conn)
        debug_tx(f"Balance updated successfully")

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
        # Create new connection with transaction
        debug_tx(f"Creating new connection with transaction")
        async with db.connect() as new_conn:
            # Begin transaction explicitly
            debug_tx(f"Beginning transaction in record_asset_transaction")
            await new_conn.execute("BEGIN TRANSACTION")
            try:
                # Insert transaction record
                await new_conn.execute(
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
                debug_tx(f"Transaction record created with ID {tx_id}")

                # Update balance
                # For debit, amount should be negative for balance update
                balance_change = amount if tx_type == 'credit' else -amount
                debug_tx(f"Updating balance with amount_change={balance_change}")
                await update_asset_balance(wallet_id, asset_id, balance_change, payment_hash, new_conn)
                debug_tx(f"Balance updated successfully")
                
                # Create result object
                result = AssetTransaction(
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
                
                # Commit transaction
                debug_tx(f"Committing transaction in record_asset_transaction")
                await new_conn.execute("COMMIT")
                debug_tx(f"Transaction committed successfully")
                return result
            except Exception as e:
                # Rollback on error
                debug_tx(f"Error in record_asset_transaction, rolling back: {str(e)}")
                await new_conn.execute("ROLLBACK")
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


# Direct implementation of process_settlement_transaction to avoid nested function issues
async def process_settlement_transaction(
    payment_hash: str,
    user_id: str,
    wallet_id: str,
    update_status: bool = True,
    notify_websocket: bool = True
) -> Dict[str, Any]:
    """
    Process a settlement transaction with proper transaction management.
    This version uses direct SQL operations to avoid nested function calls.
    
    Args:
        payment_hash: The payment hash of the invoice to settle
        user_id: User ID for the invoice owner
        wallet_id: Wallet ID for the invoice owner
        update_status: Whether to update the invoice status
        notify_websocket: Whether to send WebSocket notifications
        
    Returns:
        Dict with settlement results
    """
    logger.info(f"[SETTLEMENT] Starting direct settlement transaction for {payment_hash}")
    
    # Get the invoice first outside the transaction
    invoice = None
    async with db.connect() as conn:
        # First check if invoice exists
        row = await conn.fetchone(
            "SELECT * FROM invoices WHERE payment_hash = :payment_hash",
            {"payment_hash": payment_hash},
        )
        
        if not row:
            logger.error(f"[SETTLEMENT] No invoice found for payment hash: {payment_hash}")
            return {"success": False, "error": "Invoice not found"}
            
        # Convert row to invoice object for easier access
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
        
        logger.info(f"[SETTLEMENT] Invoice found: id={invoice.id}, status={invoice.status}")
        
        # Check if already paid
        if invoice.status == "paid":
            logger.info(f"[SETTLEMENT] Invoice {payment_hash} is already paid, returning success")
            return {"success": True, "message": "Invoice already paid", "invoice": invoice.dict()}
        
        # Track transaction state
        transaction_started = False
        transaction_committed = False
        
        try:
            # Begin transaction
            logger.info(f"[SETTLEMENT] Beginning direct transaction for {payment_hash}")
            await conn.execute("BEGIN IMMEDIATE TRANSACTION")
            transaction_started = True
            
            # Update invoice status directly if needed
            if update_status:
                logger.info(f"[SETTLEMENT] Directly updating invoice status to 'paid'")
                now = datetime.now()
                await conn.execute(
                    """
                    UPDATE invoices
                    SET status = 'paid', paid_at = :paid_at
                    WHERE id = :id
                    """,
                    {
                        "paid_at": now,
                        "id": invoice.id
                    },
                )
                
                # Update our invoice object to reflect changes
                invoice.status = "paid"
                invoice.paid_at = now
            
            # Create asset transaction record directly
            logger.info(f"[SETTLEMENT] Directly creating asset transaction record")
            tx_id = urlsafe_short_hash()
            now = datetime.now()
            memo = invoice.memo or f"Received {invoice.asset_amount} of asset {invoice.asset_id}"
            
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
                    "wallet_id": invoice.wallet_id,
                    "asset_id": invoice.asset_id,
                    "payment_hash": payment_hash,
                    "amount": invoice.asset_amount,
                    "fee": 0,
                    "memo": memo,
                    "type": "credit",
                    "created_at": now
                },
            )
            
            # Update balance directly
            logger.info(f"[SETTLEMENT] Directly updating asset balance")
            # First check if balance exists
            balance_row = await conn.fetchone(
                """
                SELECT * FROM asset_balances
                WHERE wallet_id = :wallet_id AND asset_id = :asset_id
                """,
                {
                    "wallet_id": invoice.wallet_id,
                    "asset_id": invoice.asset_id
                },
            )
            
            if balance_row:
                # Update existing balance
                logger.info(f"[SETTLEMENT] Updating existing balance")
                await conn.execute(
                    """
                    UPDATE asset_balances
                    SET balance = balance + :amount_change,
                        last_payment_hash = :payment_hash,
                        updated_at = :updated_at
                    WHERE wallet_id = :wallet_id AND asset_id = :asset_id
                    """,
                    {
                        "amount_change": invoice.asset_amount,
                        "payment_hash": payment_hash,
                        "updated_at": now,
                        "wallet_id": invoice.wallet_id,
                        "asset_id": invoice.asset_id
                    },
                )
            else:
                # Create new balance
                logger.info(f"[SETTLEMENT] Creating new balance")
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
                        "wallet_id": invoice.wallet_id,
                        "asset_id": invoice.asset_id,
                        "balance": invoice.asset_amount,
                        "last_payment_hash": payment_hash,
                        "created_at": now,
                        "updated_at": now
                    },
                )
            
            # Verify all is OK before commit
            logger.info(f"[SETTLEMENT] Verifying transaction before commit")
            verify_row = await conn.fetchone(
                "SELECT count(*) as count FROM invoices"
            )
            logger.info(f"[SETTLEMENT] Verification check: {verify_row['count']} invoices found")
            
            # Commit transaction
            logger.info(f"[SETTLEMENT] Committing direct transaction")
            await conn.execute("COMMIT")
            transaction_committed = True
            logger.info(f"[SETTLEMENT] Transaction committed successfully")
            
            # Return success response
            logger.info(f"[SETTLEMENT] Direct settlement transaction completed successfully")
            return {
                "success": True, 
                "message": "Settlement processed successfully",
                "invoice": invoice.dict(),
                "asset_id": invoice.asset_id,
                "asset_amount": invoice.asset_amount
            }
            
        except Exception as e:
            logger.error(f"[SETTLEMENT] Error in direct settlement: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Only try to rollback if we started a transaction but didn't successfully commit
            if transaction_started and not transaction_committed:
                try:
                    await conn.execute("ROLLBACK")
                    logger.info(f"[SETTLEMENT] Transaction rolled back after error")
                except Exception as rollback_error:
                    logger.error(f"[SETTLEMENT] Error during rollback: {str(rollback_error)}")
            
            return {"success": False, "error": str(e)}
