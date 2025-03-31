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

            # Get all assets from the response
            assets = [
                {
                    "name": asset.asset_genesis.name.decode('utf-8') if isinstance(asset.asset_genesis.name, bytes) else asset.asset_genesis.name,
                    "asset_id": asset.asset_genesis.asset_id.hex() if isinstance(asset.asset_genesis.asset_id, bytes) else asset.asset_genesis.asset_id,
                    "type": str(asset.asset_genesis.asset_type),
                    "amount": str(asset.amount),
                    "genesis_point": asset.asset_genesis.genesis_point,
                    "meta_hash": asset.asset_genesis.meta_hash.hex() if isinstance(asset.asset_genesis.meta_hash, bytes) else asset.asset_genesis.meta_hash,
                    "version": str(asset.version),
                    "is_spent": asset.is_spent,
                    "script_key": asset.script_key.hex() if isinstance(asset.script_key, bytes) else asset.script_key
                }
                for asset in response.assets
            ]

            # Get channel assets information
            channel_assets = await self.list_channel_assets()

            # Create a list to hold all assets (both regular and channel-specific)
            result_assets = []

            # Create a mapping of asset_id to asset info for reference
            asset_map = {asset["asset_id"]: asset for asset in assets}

            # Group channel assets by asset_id
            channel_assets_by_id = {}
            for channel_asset in channel_assets:
                asset_id = channel_asset["asset_id"]
                if asset_id not in channel_assets_by_id:
                    channel_assets_by_id[asset_id] = []
                channel_assets_by_id[asset_id].append(channel_asset)

            # Process each asset
            for asset_id, asset_channels in channel_assets_by_id.items():
                # Get base asset info
                base_asset = asset_map.get(asset_id, {
                    "asset_id": asset_id,
                    "name": asset_channels[0].get("name", "") or "Unknown Asset",
                    "type": "CHANNEL_ONLY",
                    "amount": "0",
                })

                # Add each channel as a separate asset entry
                for channel in asset_channels:
                    # Create a copy of the base asset
                    channel_asset = base_asset.copy()

                    # Add channel-specific information
                    channel_asset["channel_info"] = {
                        "channel_point": channel["channel_point"],
                        "capacity": channel["capacity"],
                        "local_balance": channel["local_balance"],
                        "remote_balance": channel["remote_balance"],
                        "peer_pubkey": channel["remote_pubkey"],  # Important for invoice creation
                        "channel_id": channel["channel_id"]
                    }

                    # Update the amount to show the channel balance
                    channel_asset["amount"] = str(channel["local_balance"])

                    # Add to result list
                    result_assets.append(channel_asset)

                # If there are no channels for an asset but it exists in assets list,
                # add it as a regular asset
                if not asset_channels and asset_id in asset_map:
                    result_assets.append(asset_map[asset_id])

            # Add any remaining assets that don't have channels
            for asset_id, asset in asset_map.items():
                if asset_id not in channel_assets_by_id:
                    result_assets.append(asset)

            return result_assets
        except Exception as e:
            logger.error(f"Failed to list assets: {str(e)}")
            return []  # Return empty list on any error

    async def list_channel_assets(self) -> List[Dict[str, Any]]:
        """
        List all Lightning channels with Taproot Assets.

        This method retrieves all Lightning channels and extracts Taproot asset information
        from channels with commitment type 4 or 6 (Taproot overlay).

        Returns:
            A list of dictionaries containing channel and asset information.
        """
        try:
            # Call the LND ListChannels endpoint
            request = lightning_pb2.ListChannelsRequest()
            response = await self.node.ln_stub.ListChannels(request, timeout=10)

            channel_assets = []

            # Process each channel
            for channel in response.channels:
                try:
                    # Check if the channel has custom_channel_data
                    if hasattr(channel, 'custom_channel_data') and channel.custom_channel_data:
                        try:
                            # Decode the custom_channel_data as UTF-8 JSON
                            asset_data = json.loads(channel.custom_channel_data.decode('utf-8'))

                            # Process each asset in the channel
                            for asset in asset_data.get("assets", []):
                                # Extract asset information from the nested structure
                                asset_utxo = asset.get("asset_utxo", {})

                                # Get asset_id from the correct location
                                asset_id = ""
                                if "asset_id" in asset_utxo:
                                    asset_id = asset_utxo["asset_id"]
                                elif "asset_genesis" in asset_utxo and "asset_id" in asset_utxo["asset_genesis"]:
                                    asset_id = asset_utxo["asset_genesis"]["asset_id"]

                                # Get name from the correct location
                                name = ""
                                if "name" in asset_utxo:
                                    name = asset_utxo["name"]
                                elif "asset_genesis" in asset_utxo and "name" in asset_utxo["asset_genesis"]:
                                    name = asset_utxo["asset_genesis"]["name"]

                                asset_info = {
                                    "asset_id": asset_id,
                                    "name": name,
                                    "channel_id": str(channel.chan_id),
                                    "channel_point": channel.channel_point,
                                    "remote_pubkey": channel.remote_pubkey,
                                    "capacity": asset.get("capacity", 0),
                                    "local_balance": asset.get("local_balance", 0),
                                    "remote_balance": asset.get("remote_balance", 0),
                                    "commitment_type": str(channel.commitment_type)
                                }

                                # Add to channel assets if it has an asset_id
                                if asset_info["asset_id"]:
                                    channel_assets.append(asset_info)
                        except Exception as e:
                            logger.debug(f"Failed to decode custom_channel_data for Chan ID {channel.chan_id}: {e}")
                except Exception as e:
                    logger.debug(f"Error processing channel {channel.channel_point}: {e}")
                    continue
            return channel_assets
        except Exception as e:
            logger.debug(f"Error in list_channel_assets: {e}")
            return []  # Return empty list instead of raising

    async def send_asset(self, asset_id: str, script_key: str, amount: int) -> Dict[str, Any]:
        """
        Process a Lightning-layer Taproot Asset transfer.
        
        For Lightning-layer Taproot assets, the transfer occurs automatically through
        the Lightning payment and HTLC. This method now simply verifies the asset
        information and returns success without trying to initiate another transfer.

        Args:
            asset_id: The ID of the asset that was transferred
            script_key: The script key from the HTLC
            amount: The amount of the asset that was transferred

        Returns:
            A dictionary confirming the asset transfer
        """
        try:
            logger.info(f"=== PROCESSING LIGHTNING ASSET TRANSFER ===")
            logger.info(f"Asset ID: {asset_id}")
            logger.info(f"Script Key: {script_key}")
            logger.info(f"Amount: {amount}")

            # For Lightning-layer Taproot assets, the transfer already happened
            # through the Lightning payment and HTLC. We just need to verify
            # the asset information and return success.
            
            # Convert asset_id to bytes for logging
            asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id
            
            # Log script key information for debugging
            script_key_bytes = bytes.fromhex(script_key) if isinstance(script_key, str) else script_key
            logger.info(f"Script key length: {len(script_key_bytes)} bytes")
            logger.info(f"Script key bytes: {script_key_bytes.hex()}")

            # Check channel assets to verify the asset exists
            channel_assets = await self.list_channel_assets()
            matching_assets = [
                ca for ca in channel_assets if ca.get("asset_id") == asset_id
            ]
            
            if matching_assets:
                logger.info(f"Asset {asset_id} found in {len(matching_assets)} channels")
                for i, asset in enumerate(matching_assets):
                    logger.info(f"Channel {i+1}: {asset.get('channel_id')}, Balance: {asset.get('local_balance')}")
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
