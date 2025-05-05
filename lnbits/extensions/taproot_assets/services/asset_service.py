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
from ..wallets.taproot_factory import TaprootAssetsFactory
from ..error_utils import log_error, handle_grpc_error, raise_http_exception
from ..crud import (
    get_assets,
    get_asset,
    get_asset_balance,
    get_wallet_asset_balances,
    get_asset_transactions
)
from ..notification_service import NotificationService


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
        try:
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
        except Exception as e:
            logger.error(f"Failed to list assets: {str(e)}")
            return []  # Return empty list on error
    
    @staticmethod
    async def get_asset(asset_id: str, wallet: WalletTypeInfo) -> Dict[str, Any]:
        """
        Get a specific Taproot Asset by ID with user balance.
        
        Args:
            asset_id: The asset ID
            wallet: The wallet information
            
        Returns:
            Dict[str, Any]: Asset information with balance
            
        Raises:
            HTTPException: If the asset is not found or doesn't belong to the user
        """
        # Get user for permission check
        user = await get_user(wallet.wallet.user)
        if not user:
            raise_http_exception(
                status_code=HTTPStatus.NOT_FOUND,
                detail="User not found",
            )
            
        asset = await get_asset(asset_id)

        if not asset:
            raise_http_exception(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Asset not found",
            )

        if asset.user_id != user.id:
            raise_http_exception(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Not your asset",
            )
        
        # Get user's balance for this asset
        balance = await get_asset_balance(wallet.wallet.id, asset.asset_id)
        
        # Add user balance to the response
        asset_dict = asset.dict()
        asset_dict["user_balance"] = balance.balance if balance else 0
        
        return asset_dict
    
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
        try:
            balances = await get_wallet_asset_balances(wallet.wallet.id)
            return balances
        except Exception as e:
            logger.error(f"Error retrieving asset balances: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve asset balances: {str(e)}",
            )
    
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
        try:
            balance = await get_asset_balance(wallet.wallet.id, asset_id)
            if not balance:
                return {"wallet_id": wallet.wallet.id, "asset_id": asset_id, "balance": 0}
            return balance
        except Exception as e:
            logger.error(f"Error retrieving asset balance: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve asset balance: {str(e)}",
            )
    
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
        try:
            transactions = await get_asset_transactions(wallet.wallet.id, asset_id, limit)
            return transactions
        except Exception as e:
            logger.error(f"Error retrieving asset transactions: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve asset transactions: {str(e)}",
            )
