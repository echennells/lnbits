"""
Settings-related CRUD operations for Taproot Assets extension.
"""
from typing import Optional
from lnbits.helpers import urlsafe_short_hash

from ..models import TaprootSettings
from ..db import db, get_table_name
from ..db_utils import with_transaction
from .utils import get_record_by_id

@with_transaction
async def get_or_create_settings(conn=None) -> TaprootSettings:
    """
    Get or create Taproot Assets extension settings.
    
    Args:
        conn: Optional database connection to reuse
        
    Returns:
        TaprootSettings: The settings object
    """
    row = await conn.fetchone(
        f"SELECT * FROM {get_table_name('settings')} LIMIT 1", 
        {}, 
        TaprootSettings
    )
    if row:
        return row

    # Create default settings with ID included
    settings_id = urlsafe_short_hash()
    
    # Insert using direct SQL to avoid the model issue
    await conn.execute(
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
    return await conn.fetchone(
        f"SELECT * FROM {get_table_name('settings')} LIMIT 1", 
        {}, 
        TaprootSettings
    )


@with_transaction
async def update_settings(settings: TaprootSettings, conn=None) -> TaprootSettings:
    """
    Update Taproot Assets extension settings.
    
    Args:
        settings: The settings object to update
        conn: Optional database connection to reuse
        
    Returns:
        TaprootSettings: The updated settings object
    """
    # Get existing settings ID or create a new one
    row = await conn.fetchone(
        f"SELECT id FROM {get_table_name('settings')} LIMIT 1",
        {},
        None
    )
    
    if row:
        # Update existing settings
        # Set the ID from the existing record
        settings.id = row["id"]
        await conn.update(
            get_table_name("settings"),
            settings,
            "WHERE id = :id"
        )
    else:
        # Create new settings with a generated ID
        settings.id = urlsafe_short_hash()
        await conn.insert(get_table_name("settings"), settings)
    
    # Return the updated settings
    return await conn.fetchone(
        f"SELECT * FROM {get_table_name('settings')} LIMIT 1", 
        {}, 
        TaprootSettings
    )
