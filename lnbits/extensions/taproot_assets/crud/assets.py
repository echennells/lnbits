"""
Asset-related CRUD operations for Taproot Assets extension.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from lnbits.helpers import urlsafe_short_hash

from ..models import TaprootAsset
from ..db import db, get_table_name
from .utils import get_record_by_id, get_records_by_field

async def create_asset(asset_data: Dict[str, Any], user_id: str) -> TaprootAsset:
    """
    Create a new Taproot Asset record.
    
    Args:
        asset_data: Dictionary containing asset data
        user_id: The ID of the user creating the asset
        
    Returns:
        TaprootAsset: The created asset
    """
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
    return await get_records_by_field("assets", "user_id", user_id, TaprootAsset, conn=conn)


async def get_asset(asset_id: str, conn=None) -> Optional[TaprootAsset]:
    """
    Get a specific Taproot Asset by ID.
    
    Args:
        asset_id: The asset ID to look up
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootAsset]: The asset if found, None otherwise
    """
    return await get_record_by_id("assets", asset_id, TaprootAsset, conn)
