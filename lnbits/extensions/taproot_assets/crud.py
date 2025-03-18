import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from loguru import logger

from lnbits.db import Connection, Database
from lnbits.helpers import urlsafe_short_hash

from .models import TaprootSettings, TaprootAsset, TaprootInvoice

# Create a database instance for the extension
db = Database("ext_taproot_assets")


async def get_or_create_settings() -> TaprootSettings:
    """Get or create Taproot Assets extension settings."""
    async with db.connect() as conn:
        row = await conn.fetchone("SELECT * FROM taproot_assets.settings LIMIT 1")
        if row:
            return TaprootSettings(**dict(row))

        # Create default settings
        settings = TaprootSettings()
        settings_id = urlsafe_short_hash()
        await conn.execute(
            """
            INSERT INTO taproot_assets.settings (
                id, tapd_host, tapd_network, tapd_tls_cert_path,
                tapd_macaroon_path, tapd_macaroon_hex,
                lnd_macaroon_path, lnd_macaroon_hex
            )
            VALUES (:id, :tapd_host, :tapd_network, :tapd_tls_cert_path,
                    :tapd_macaroon_path, :tapd_macaroon_hex,
                    :lnd_macaroon_path, :lnd_macaroon_hex)
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
            },
        )
        return settings

async def update_settings(settings: TaprootSettings) -> TaprootSettings:
    """Update Taproot Assets extension settings."""
    async with db.connect() as conn:
        # Get existing settings ID or create a new one
        row = await conn.fetchone("SELECT id FROM taproot_assets.settings LIMIT 1")
        settings_id = row["id"] if row else urlsafe_short_hash()

        await conn.execute(
            """
            INSERT OR REPLACE INTO taproot_assets.settings (
                id, tapd_host, tapd_network, tapd_tls_cert_path,
                tapd_macaroon_path, tapd_macaroon_hex,
                lnd_macaroon_path, lnd_macaroon_hex
            )
            VALUES (:id, :tapd_host, :tapd_network, :tapd_tls_cert_path,
                    :tapd_macaroon_path, :tapd_macaroon_hex,
                    :lnd_macaroon_path, :lnd_macaroon_hex)
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
            },
        )
        return settings

async def create_asset(asset_data: Dict[str, Any], user_id: str) -> TaprootAsset:
    """Create a new Taproot Asset record."""
    async with db.connect() as conn:
        asset_id = urlsafe_short_hash()
        now = datetime.now()

        # Convert channel_info to JSON string if present
        channel_info_json = json.dumps(asset_data.get("channel_info")) if asset_data.get("channel_info") else None

        # Changed from tuple to dictionary with named parameters
        await conn.execute(
            """
            INSERT INTO taproot_assets.assets (
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

        # Create a TaprootAsset object from the inserted data
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
            "SELECT * FROM taproot_assets.assets WHERE user_id = :user_id ORDER BY created_at DESC",
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
        # Changed to use named parameters for consistency
        row = await conn.fetchone(
            "SELECT * FROM taproot_assets.assets WHERE id = :id",
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
    buy_quote: Optional[Dict[str, Any]] = None,
) -> TaprootInvoice:
    """Create a new Taproot Asset invoice."""
    async with db.connect() as conn:
        invoice_id = urlsafe_short_hash()
        now = datetime.now()
        expires_at = now + timedelta(seconds=expiry) if expiry else None

        # Convert buy_quote to JSON string if present
        try:
            # Ensure buy_quote is a dictionary
            if buy_quote and not isinstance(buy_quote, dict):
                logger.warning(f"buy_quote is not a dict, converting from {type(buy_quote)}")
                if isinstance(buy_quote, (list, tuple)):
                    buy_quote = {"items": list(buy_quote)}
                else:
                    buy_quote = {"value": str(buy_quote)}

            buy_quote_json = json.dumps(buy_quote) if buy_quote else None
        except Exception as e:
            logger.warning(f"Error serializing buy_quote: {e}")
            buy_quote_json = None

        # CHANGED: Use named parameters with a dictionary instead of positional parameters
        await conn.execute(
            """
            INSERT INTO taproot_assets.invoices (
                id, payment_hash, payment_request, asset_id, asset_amount,
                satoshi_amount, memo, status, user_id, wallet_id,
                created_at, expires_at, buy_quote
            )
            VALUES (
                :id, :payment_hash, :payment_request, :asset_id, :asset_amount,
                :satoshi_amount, :memo, :status, :user_id, :wallet_id,
                :created_at, :expires_at, :buy_quote
            )
            """,
            {
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
                "buy_quote": buy_quote_json,
            },
        )

        # Create a TaprootInvoice object from the inserted data
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
            buy_quote=buy_quote,
        )


async def get_invoice(invoice_id: str) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by ID."""
    async with db.connect() as conn:
        # Changed to use named parameters for consistency
        row = await conn.fetchone(
            "SELECT * FROM taproot_assets.invoices WHERE id = :id",
            {"id": invoice_id},
        )

        if not row:
            return None

        # Parse buy_quote JSON if present
        buy_quote = json.loads(row["buy_quote"]) if row["buy_quote"] else None

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
            buy_quote=buy_quote,
        )


async def get_invoice_by_payment_hash(payment_hash: str) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by payment hash."""
    async with db.connect() as conn:
        # Changed to use named parameters for consistency
        row = await conn.fetchone(
            "SELECT * FROM taproot_assets.invoices WHERE payment_hash = :payment_hash",
            {"payment_hash": payment_hash},
        )

        if not row:
            return None

        # Parse buy_quote JSON if present
        buy_quote = json.loads(row["buy_quote"]) if row["buy_quote"] else None

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
            buy_quote=buy_quote,
        )


async def update_invoice_status(invoice_id: str, status: str) -> Optional[TaprootInvoice]:
    """Update the status of a Taproot Asset invoice."""
    async with db.connect() as conn:
        now = datetime.now()
        paid_at = now if status == "paid" else None

        # Changed to use named parameters for consistency
        await conn.execute(
            """
            UPDATE taproot_assets.invoices
            SET status = :status, paid_at = :paid_at
            WHERE id = :id
            """,
            {
                "status": status,
                "paid_at": paid_at,
                "id": invoice_id
            },
        )

        return await get_invoice(invoice_id)

async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
    """Get all Taproot Asset invoices for a user."""
    async with db.connect() as conn:
        rows = await conn.fetchall(
            "SELECT * FROM taproot_assets.invoices WHERE user_id = :user_id ORDER BY created_at DESC",
            {"user_id": user_id},
        )

        invoices = []
        for row in rows:
            # Parse buy_quote JSON if present
            buy_quote = json.loads(row["buy_quote"]) if row["buy_quote"] else None

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
                buy_quote=buy_quote,
            )
            invoices.append(invoice)

        return invoices
