import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from lnbits.db import Connection, Database
from lnbits.helpers import urlsafe_short_hash

from .models import TaprootSettings, TaprootAsset, TaprootInvoice

# Create a database instance for the extension
db = Database("ext_taproot_assets")


async def get_or_create_settings(db: Connection) -> TaprootSettings:
    """Get or create Taproot Assets extension settings."""
    row = await db.fetchone("SELECT * FROM settings LIMIT 1")
    if row:
        return TaprootSettings(**dict(row))
    
    # Create default settings
    settings = TaprootSettings()
    settings_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO settings (
            id, tapd_host, tapd_network, tapd_tls_cert_path, 
            tapd_macaroon_path, tapd_macaroon_hex, 
            lnd_macaroon_path, lnd_macaroon_hex
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            settings_id,
            settings.tapd_host,
            settings.tapd_network,
            settings.tapd_tls_cert_path,
            settings.tapd_macaroon_path,
            settings.tapd_macaroon_hex,
            settings.lnd_macaroon_path,
            settings.lnd_macaroon_hex,
        ),
    )
    return settings


async def update_settings(settings: TaprootSettings, db: Connection) -> TaprootSettings:
    """Update Taproot Assets extension settings."""
    # Get existing settings ID or create a new one
    row = await db.fetchone("SELECT id FROM settings LIMIT 1")
    settings_id = row["id"] if row else urlsafe_short_hash()
    
    await db.execute(
        """
        INSERT OR REPLACE INTO settings (
            id, tapd_host, tapd_network, tapd_tls_cert_path, 
            tapd_macaroon_path, tapd_macaroon_hex, 
            lnd_macaroon_path, lnd_macaroon_hex
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            settings_id,
            settings.tapd_host,
            settings.tapd_network,
            settings.tapd_tls_cert_path,
            settings.tapd_macaroon_path,
            settings.tapd_macaroon_hex,
            settings.lnd_macaroon_path,
            settings.lnd_macaroon_hex,
        ),
    )
    return settings


async def create_asset(asset_data: Dict[str, Any], user_id: str, db: Connection) -> TaprootAsset:
    """Create a new Taproot Asset record."""
    asset_id = urlsafe_short_hash()
    now = datetime.now()
    
    # Convert channel_info to JSON string if present
    channel_info_json = json.dumps(asset_data.get("channel_info")) if asset_data.get("channel_info") else None
    
    await db.execute(
        """
        INSERT INTO assets (
            id, name, asset_id, type, amount, genesis_point, meta_hash,
            version, is_spent, script_key, channel_info, user_id,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            asset_data.get("name", "Unknown"),
            asset_data["asset_id"],
            asset_data["type"],
            asset_data["amount"],
            asset_data["genesis_point"],
            asset_data["meta_hash"],
            asset_data["version"],
            asset_data["is_spent"],
            asset_data["script_key"],
            channel_info_json,
            user_id,
            now,
            now,
        ),
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


async def get_assets(user_id: str, db: Connection) -> List[TaprootAsset]:
    """Get all Taproot Assets for a user."""
    rows = await db.fetchall(
        "SELECT * FROM taproot_assets.assets WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
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


async def get_asset(asset_id: str, db: Connection) -> Optional[TaprootAsset]:
    """Get a specific Taproot Asset by ID."""
    row = await db.fetchone(
        "SELECT * FROM taproot_assets.assets WHERE id = ?", (asset_id,)
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
    db: Connection = None,
) -> TaprootInvoice:
    """Create a new Taproot Asset invoice."""
    invoice_id = urlsafe_short_hash()
    now = datetime.now()
    expires_at = now + timedelta(seconds=expiry) if expiry else None
    
    # Convert buy_quote to JSON string if present
    buy_quote_json = json.dumps(buy_quote) if buy_quote else None
    
    await db.execute(
        """
        INSERT INTO taproot_assets.invoices (
            id, payment_hash, payment_request, asset_id, asset_amount,
            satoshi_amount, memo, status, user_id, wallet_id,
            created_at, expires_at, buy_quote
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_id,
            payment_hash,
            payment_request,
            asset_id,
            asset_amount,
            satoshi_amount,
            memo,
            "pending",
            user_id,
            wallet_id,
            now,
            expires_at,
            buy_quote_json,
        ),
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


async def get_invoice(invoice_id: str, db: Connection) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by ID."""
    row = await db.fetchone(
        "SELECT * FROM taproot_assets.invoices WHERE id = ?", (invoice_id,)
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


async def get_invoice_by_payment_hash(payment_hash: str, db: Connection) -> Optional[TaprootInvoice]:
    """Get a specific Taproot Asset invoice by payment hash."""
    row = await db.fetchone(
        "SELECT * FROM taproot_assets.invoices WHERE payment_hash = ?", (payment_hash,)
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


async def update_invoice_status(invoice_id: str, status: str, db: Connection) -> Optional[TaprootInvoice]:
    """Update the status of a Taproot Asset invoice."""
    now = datetime.now()
    paid_at = now if status == "paid" else None
    
    await db.execute(
        """
        UPDATE taproot_assets.invoices
        SET status = ?, paid_at = ?
        WHERE id = ?
        """,
        (status, paid_at, invoice_id),
    )
    
    return await get_invoice(invoice_id, db)


async def get_user_invoices(user_id: str, db: Connection) -> List[TaprootInvoice]:
    """Get all Taproot Asset invoices for a user."""
    rows = await db.fetchall(
        "SELECT * FROM taproot_assets.invoices WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
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
