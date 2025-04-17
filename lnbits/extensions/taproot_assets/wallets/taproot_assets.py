import json
from typing import List, Dict, Any, Optional
from loguru import logger

from .taproot_adapter import (
    taprootassets_pb2,
    lightning_pb2
)

class TaprootAssetManager:
    """
    Handles Taproot Asset management functionality.
    This class is responsible for listing and managing Taproot Assets.
    """

    def __init__(self, node):
        """
        Initialize the asset manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node

    async def list_assets(self) -> List[Dict[str, Any]]:
        """List all Taproot Assets."""
        try:
            # Get all assets from tapd
            request = taprootassets_pb2.ListAssetRequest(
                with_witness=False,
                include_spent=False,
                include_leased=True,
                include_unconfirmed_mints=True
            )
            response = await self.node.stub.ListAssets(request, timeout=10)

            # Convert response assets to dictionary format
            assets = []
            for asset in response.assets:
                assets.append({
                    "name": asset.asset_genesis.name.decode('utf-8') if isinstance(asset.asset_genesis.name, bytes) else asset.asset_genesis.name,
                    "asset_id": asset.asset_genesis.asset_id.hex() if isinstance(asset.asset_genesis.asset_id, bytes) else asset.asset_genesis.asset_id,
                    "type": str(asset.asset_genesis.asset_type),
                    "amount": str(asset.amount),
                    "genesis_point": asset.asset_genesis.genesis_point,
                    "meta_hash": asset.asset_genesis.meta_hash.hex() if isinstance(asset.asset_genesis.meta_hash, bytes) else asset.asset_genesis.meta_hash,
                    "version": str(asset.version),
                    "is_spent": asset.is_spent,
                    "script_key": asset.script_key.hex() if isinstance(asset.script_key, bytes) else asset.script_key
                })

            # Get channel assets
            channel_assets = await self.list_channel_assets()

            # Create asset map for lookup
            asset_map = {asset["asset_id"]: asset for asset in assets}
            
            # Group channel assets by asset_id
            channel_assets_by_id = {}
            for channel_asset in channel_assets:
                asset_id = channel_asset["asset_id"]
                if asset_id not in channel_assets_by_id:
                    channel_assets_by_id[asset_id] = []
                channel_assets_by_id[asset_id].append(channel_asset)

            # Process assets with channels
            result_assets = []
            
            # Add assets with channels
            for asset_id, channels in channel_assets_by_id.items():
                base_asset = asset_map.get(asset_id, {
                    "asset_id": asset_id,
                    "name": channels[0].get("name", "") or "Unknown Asset",
                    "type": "CHANNEL_ONLY",
                    "amount": "0",
                })
                
                # Add each channel as a separate asset entry
                for channel in channels:
                    asset_with_channel = base_asset.copy()
                    asset_with_channel["channel_info"] = {
                        "channel_point": channel["channel_point"],
                        "capacity": channel["capacity"],
                        "local_balance": channel["local_balance"],
                        "remote_balance": channel["remote_balance"],
                        "peer_pubkey": channel["remote_pubkey"],
                        "channel_id": channel["channel_id"],
                        "active": channel.get("active", True)  # Add active status
                    }
                    asset_with_channel["amount"] = str(channel["local_balance"])
                    result_assets.append(asset_with_channel)
            
            # We're not adding non-channel assets anymore, per the requirements
            # The commented code below would add regular assets without channels
            # which we now want to filter out
            
            # # Add remaining assets without channels
            # for asset_id, asset in asset_map.items():
            #     if asset_id not in channel_assets_by_id:
            #         result_assets.append(asset)

            return result_assets
        except Exception as e:
            logger.error(f"Failed to list assets: {str(e)}")
            return []  # Return empty list on error

    async def list_channel_assets(self) -> List[Dict[str, Any]]:
        """
        List all Lightning channels with Taproot Assets.

        Returns:
            A list of dictionaries containing channel and asset information.
        """
        try:
            # Get channels from LND
            request = lightning_pb2.ListChannelsRequest()
            response = await self.node.ln_stub.ListChannels(request, timeout=10)

            channel_assets = []

            # Process each channel
            for channel in response.channels:
                # Skip channels without custom_channel_data
                if not hasattr(channel, 'custom_channel_data') or not channel.custom_channel_data:
                    continue
                    
                try:
                    # Parse JSON data
                    asset_data = json.loads(channel.custom_channel_data.decode('utf-8'))
                    
                    # Process each asset in the channel
                    for asset in asset_data.get("assets", []):
                        asset_utxo = asset.get("asset_utxo", {})
                        
                        # Extract asset ID
                        asset_id = ""
                        if "asset_id" in asset_utxo:
                            asset_id = asset_utxo["asset_id"]
                        elif "asset_genesis" in asset_utxo and "asset_id" in asset_utxo["asset_genesis"]:
                            asset_id = asset_utxo["asset_genesis"]["asset_id"]
                        
                        # Skip entries without asset ID
                        if not asset_id:
                            continue
                            
                        # Extract name
                        name = ""
                        if "name" in asset_utxo:
                            name = asset_utxo["name"]
                        elif "asset_genesis" in asset_utxo and "name" in asset_utxo["asset_genesis"]:
                            name = asset_utxo["asset_genesis"]["name"]
                        
                        # Create asset info dictionary
                        asset_info = {
                            "asset_id": asset_id,
                            "name": name,
                            "channel_id": str(channel.chan_id),
                            "channel_point": channel.channel_point,
                            "remote_pubkey": channel.remote_pubkey,
                            "capacity": asset.get("capacity", 0),
                            "local_balance": asset.get("local_balance", 0),
                            "remote_balance": asset.get("remote_balance", 0),
                            "commitment_type": str(channel.commitment_type),
                            "active": channel.active  # Include active status from channel
                        }
                        
                        channel_assets.append(asset_info)
                except Exception as e:
                    logger.debug(f"Failed to process channel {channel.channel_point}: {e}")
                    continue
                    
            return channel_assets
        except Exception as e:
            logger.debug(f"Error listing channel assets: {e}")
            return []

    async def send_asset(self, asset_id: str, script_key: str, amount: int) -> Dict[str, Any]:
        """
        Process a Lightning-layer Taproot Asset transfer.
        
        For Lightning-layer Taproot assets, the transfer occurs automatically through
        the Lightning payment and HTLC. This method verifies the asset information and
        returns success without initiating another transfer.

        Args:
            asset_id: The ID of the asset that was transferred
            script_key: The script key from the HTLC
            amount: The amount of the asset that was transferred

        Returns:
            A dictionary confirming the asset transfer
        """
        try:
            logger.info(f"Processing Lightning asset transfer - ID: {asset_id}, Amount: {amount}")
            
            # Verify the asset exists
            if asset_id:
                channel_assets = await self.list_channel_assets()
                matching_assets = [ca for ca in channel_assets if ca.get("asset_id") == asset_id]
                
                if matching_assets:
                    logger.info(f"Asset {asset_id} found in {len(matching_assets)} channels")
                else:
                    logger.warning(f"Asset {asset_id} not found in any channels")
            
            # Return success response
            return {
                "success": True,
                "asset_id": asset_id,
                "amount": amount,
                "script_key": script_key,
                "method": "lightning_layer"
            }

        except Exception as e:
            logger.error(f"Failed to process asset transfer: {str(e)}", exc_info=True)
            raise Exception(f"Failed to process asset transfer: {str(e)}")
