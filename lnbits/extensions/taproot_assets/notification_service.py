"""
Notification service for Taproot Assets extension.
Centralizes WebSocket notification logic.
"""
import json
from typing import Dict, Any, List, Optional, Union
from loguru import logger

from lnbits.core.services.websockets import websocket_manager
from .logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    WEBSOCKET, ASSET
)

class NotificationService:
    """
    Service for sending notifications to users about Taproot Assets events.
    Centralizes notification logic and provides batch notification capabilities.
    """
    
    @staticmethod
    async def notify_invoice_update(user_id: str, invoice_data: Dict[str, Any]) -> bool:
        """
        Send invoice update notification to a user.
        
        Args:
            user_id: ID of the user to notify
            invoice_data: Invoice data to send
            
        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not user_id or not invoice_data:
            log_warning(WEBSOCKET, "Cannot send invoice notification with empty user_id or data")
            return False
            
        try:
            # Create a unique item_id for this user and event type
            item_id = f"taproot-assets-invoices-{user_id}"
            
            # Prepare message with type and data
            message = json.dumps({
                "type": "invoice_update",
                "data": invoice_data
            })
            
            # Send directly through core WebSocket manager
            await websocket_manager.send_data(message, item_id)
            log_debug(WEBSOCKET, f"Sent invoice update notification for user {user_id}")
            return True
        except Exception as e:
            log_error(WEBSOCKET, f"Error sending invoice update: {str(e)}")
            return False
    
    @staticmethod
    async def notify_payment_update(user_id: str, payment_data: Dict[str, Any]) -> bool:
        """
        Send payment update notification to a user.
        
        Args:
            user_id: ID of the user to notify
            payment_data: Payment data to send
            
        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not user_id or not payment_data:
            log_warning(WEBSOCKET, "Cannot send payment notification with empty user_id or data")
            return False
            
        try:
            # Create a unique item_id for this user and event type
            item_id = f"taproot-assets-payments-{user_id}"
            
            # Prepare message with type and data
            message = json.dumps({
                "type": "payment_update",
                "data": payment_data
            })
            
            # Send directly through core WebSocket manager
            await websocket_manager.send_data(message, item_id)
            log_debug(WEBSOCKET, f"Sent payment update notification for user {user_id}")
            return True
        except Exception as e:
            log_error(WEBSOCKET, f"Error sending payment update: {str(e)}")
            return False
    
    @staticmethod
    async def notify_assets_update(user_id: str, assets_data: List[Dict[str, Any]]) -> bool:
        """
        Send assets update notification to a user.
        
        Args:
            user_id: ID of the user to notify
            assets_data: List of asset data to send
            
        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not user_id or not assets_data:
            log_warning(WEBSOCKET, "Cannot send assets notification with empty user_id or data")
            return False
            
        try:
            # Create a unique item_id for this user and event type
            item_id = f"taproot-assets-balances-{user_id}"
            
            # Prepare message with type and data
            message = json.dumps({
                "type": "assets_update",
                "data": assets_data
            })
            
            # Send directly through core WebSocket manager
            await websocket_manager.send_data(message, item_id)
            log_debug(WEBSOCKET, f"Sent assets update notification for user {user_id}")
            return True
        except Exception as e:
            log_error(WEBSOCKET, f"Error sending assets update: {str(e)}")
            return False
    
    @staticmethod
    async def notify_batch_updates(
        user_id: str, 
        updates: Dict[str, Union[Dict[str, Any], List[Dict[str, Any]]]]
    ) -> Dict[str, bool]:
        """
        Send multiple notifications to a user in one batch.
        
        Args:
            user_id: ID of the user to notify
            updates: Dictionary mapping update types to their data
                     Supported types: "invoice", "payment", "assets"
                     
        Returns:
            Dict mapping update types to success status
        """
        results = {}
        
        if not user_id:
            log_warning(WEBSOCKET, "Cannot send notifications with empty user_id")
            return {k: False for k in updates.keys()}
        
        log_info(WEBSOCKET, f"Sending batch notifications to user {user_id}: {', '.join(updates.keys())}")
        
        # Process each update type
        for update_type, data in updates.items():
            if not data:
                log_warning(WEBSOCKET, f"Empty data for {update_type} notification")
                results[update_type] = False
                continue
                
            try:
                if update_type == "invoice" and isinstance(data, dict):
                    results[update_type] = await NotificationService.notify_invoice_update(user_id, data)
                elif update_type == "payment" and isinstance(data, dict):
                    results[update_type] = await NotificationService.notify_payment_update(user_id, data)
                elif update_type == "assets" and isinstance(data, list):
                    results[update_type] = await NotificationService.notify_assets_update(user_id, data)
                else:
                    log_warning(WEBSOCKET, f"Unknown notification type: {update_type}")
                    results[update_type] = False
            except Exception as e:
                log_error(WEBSOCKET, f"Error sending {update_type} notification: {str(e)}")
                results[update_type] = False
        
        return results
    
    @staticmethod
    async def notify_transaction_complete(
        user_id: str,
        wallet_id: str,
        payment_hash: str,
        asset_id: str,
        asset_amount: int,
        tx_type: str,
        description: Optional[str] = None,
        fee_sats: int = 0,
        is_internal: bool = False,
        is_self_payment: bool = False
    ) -> Dict[str, bool]:
        """
        Send all notifications related to a completed transaction.
        This includes payment notification and assets update.
        
        Args:
            user_id: ID of the user to notify
            wallet_id: ID of the wallet
            payment_hash: Payment hash of the transaction
            asset_id: Asset ID involved in the transaction
            asset_amount: Amount of the asset
            tx_type: Transaction type ("credit" or "debit")
            description: Optional description for the transaction
            fee_sats: Fee in satoshis
            is_internal: Whether this is an internal payment
            is_self_payment: Whether this is a self-payment
            
        Returns:
            Dict mapping update types to success status
        """
        from .tapd.taproot_wallet import TaprootWalletExtension
        from .crud.balances import get_asset_balance
        
        log_info(WEBSOCKET, f"Preparing transaction complete notifications for user {user_id}")
        
        updates = {}
        
        # Create payment data for notification
        payment_data = {
            "payment_hash": payment_hash,
            "asset_id": asset_id,
            "asset_amount": asset_amount,
            "fee_sats": fee_sats,
            "description": description or "",  # Use empty string if no description provided
            "status": "completed",
            "internal_payment": is_internal,
            "self_payment": is_self_payment
        }
        
        # Add payment notification
        updates["payment"] = payment_data
        
        # Get updated assets for notification
        try:
            # Get assets directly from the database instead of using the wallet
            from .crud.assets import get_assets
            
            log_debug(ASSET, f"Fetching assets for user {user_id} for notification")
            
            # Get assets for this user
            assets = await get_assets(user_id)
            
            # Filter to only include assets with channel info
            filtered_assets = [asset for asset in assets if asset.get("channel_info")]
            
            # Add user balance information
            for asset in filtered_assets:
                asset_id_check = asset.get("asset_id")
                if asset_id_check:
                    balance = await get_asset_balance(wallet_id, asset_id_check)
                    asset["user_balance"] = balance.balance if balance else 0
            
            if filtered_assets:
                log_debug(ASSET, f"Including {len(filtered_assets)} assets in notification")
                updates["assets"] = filtered_assets
        except Exception as e:
            log_error(ASSET, f"Failed to fetch assets for notification: {str(e)}")
        
        # Send all notifications in one batch
        return await NotificationService.notify_batch_updates(user_id, updates)
