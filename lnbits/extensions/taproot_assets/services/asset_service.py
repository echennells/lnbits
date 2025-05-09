"""
Asset service for Taproot Assets extension.
Handles asset-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
from http import HTTPStatus
from loguru import logger

from lnbits.core.models import WalletTypeInfo, User
from lnbits.core.crud import get_user

from ..models import TaprootAsset, AssetBalance, AssetTransaction
from ..tapd.taproot_factory import TaprootAssetsFactory
from ..error_utils import raise_http_exception, ErrorContext
from ..logging_utils import API, ASSET
# Import from crud re-exports
from ..crud import (
    get_assets,
    get_asset_balance,
    get_wallet_asset_balances,
    get_asset_transactions
)
from .notification_service import NotificationService


class AssetService:
    """
    Service for handling Taproot Assets.
    This service encapsulates asset-related business logic.
    """
    
    @staticmethod
    async def list_assets(wallet: WalletTypeInfo) -> List[Dict[str, Any]]:
        """
        List all Taproot Assets for the current user with balance information.
        
        Args:
            wallet: The wallet information
            
        Returns:
            List[Dict[str, Any]]: List of assets with balance information
        """
        with ErrorContext("list_assets", ASSET):
            # Create a wallet instance using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )

            # Get assets from tapd
            assets_data = await taproot_wallet.list_assets()
            
            # Get user information
            user = await get_user(wallet.wallet.user)
            if not user or not user.wallets:
                return []
            
            # Get user's wallet asset balances
            wallet_balances = {}
            for user_wallet in user.wallets:
                balances = await get_wallet_asset_balances(user_wallet.id)
                for balance in balances:
                    wallet_balances[balance.asset_id] = balance.dict()
            
            # Enhance the assets data with user balance information
            for asset in assets_data:
                asset_id = asset.get("asset_id")
                if asset_id in wallet_balances:
                    asset["user_balance"] = wallet_balances[asset_id]["balance"]
                else:
                    asset["user_balance"] = 0
                    
            # Send WebSocket notification with assets data using NotificationService
            if assets_data:
                await NotificationService.notify_assets_update(wallet.wallet.user, assets_data)
                
            return assets_data
    
    @staticmethod
    async def get_asset_balances(wallet: WalletTypeInfo) -> List[AssetBalance]:
        """
        Get all asset balances for the current wallet.
        
        Args:
            wallet: The wallet information
            
        Returns:
            List[AssetBalance]: List of asset balances
            
        Raises:
            HTTPException: If there's an error retrieving asset balances
        """
        with ErrorContext("get_asset_balances", ASSET):
            balances = await get_wallet_asset_balances(wallet.wallet.id)
            return balances
    
    @staticmethod
    async def get_asset_balance(asset_id: str, wallet: WalletTypeInfo) -> Dict[str, Any]:
        """
        Get the balance for a specific asset in the current wallet.
        
        Args:
            asset_id: The asset ID
            wallet: The wallet information
            
        Returns:
            Dict[str, Any]: Asset balance information
            
        Raises:
            HTTPException: If there's an error retrieving the asset balance
        """
        with ErrorContext("get_asset_balance", ASSET):
            balance = await get_asset_balance(wallet.wallet.id, asset_id)
            if not balance:
                return {"wallet_id": wallet.wallet.id, "asset_id": asset_id, "balance": 0}
            return balance
    
    @staticmethod
    async def get_asset_transactions(
        wallet: WalletTypeInfo,
        asset_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AssetTransaction]:
        """
        Get asset transactions for the current wallet.
        
        Args:
            wallet: The wallet information
            asset_id: Optional asset ID to filter transactions
            limit: Maximum number of transactions to return
            
        Returns:
            List[AssetTransaction]: List of asset transactions
            
        Raises:
            HTTPException: If there's an error retrieving asset transactions
        """
        with ErrorContext("get_asset_transactions", ASSET):
            transactions = await get_asset_transactions(wallet.wallet.id, asset_id, limit)
            return transactions
