"""
WebSocket handler for Taproot Assets extension.
Integrates with LNBits core WebSocket functionality.
"""
import json
from typing import Dict, Any, List, Optional
from loguru import logger

from lnbits.core.services.websockets import websocket_manager


class TaprootAssetsNotifier:
    """
    Sends notifications about Taproot Assets extension events
    through the LNBits WebSocket manager.
    """
    
    @staticmethod
    async def notify_invoice_update(user_id: str, invoice_data: Dict[str, Any]) -> bool:
        """
        Notify about invoice status update.
        
        Args:
            user_id: ID of the user to notify
            invoice_data: Invoice data to send
            
        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not user_id or not invoice_data:
            logger.warning("Cannot send invoice notification with empty user_id or data")
            return False
            
        try:
            # Create a unique item_id for this user and event type
            item_id = f"taproot-assets-invoices-{user_id}"
            
            # Prepare message with type and data
            message = json.dumps({
                "type": "invoice_update",
                "data": invoice_data
            })
            
            # Send through core WebSocket manager
            await websocket_manager.send_data(message, item_id)
            logger.debug(f"Sent invoice update notification for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending invoice update: {str(e)}")
            return False
    
    @staticmethod
    async def notify_payment_update(user_id: str, payment_data: Dict[str, Any]) -> bool:
        """
        Notify about payment status update.
        
        Args:
            user_id: ID of the user to notify
            payment_data: Payment data to send
            
        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not user_id or not payment_data:
            logger.warning("Cannot send payment notification with empty user_id or data")
            return False
            
        try:
            # Create a unique item_id for this user and event type
            item_id = f"taproot-assets-payments-{user_id}"
            
            # Prepare message with type and data
            message = json.dumps({
                "type": "payment_update",
                "data": payment_data
            })
            
            # Send through core WebSocket manager
            await websocket_manager.send_data(message, item_id)
            logger.debug(f"Sent payment update notification for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending payment update: {str(e)}")
            return False
    
    @staticmethod
    async def notify_assets_update(user_id: str, assets_data: List[Dict[str, Any]]) -> bool:
        """
        Notify about assets balance update.
        
        Args:
            user_id: ID of the user to notify
            assets_data: List of asset data to send
            
        Returns:
            bool: True if notification was sent successfully, False otherwise
        """
        if not user_id or not assets_data:
            logger.warning("Cannot send assets notification with empty user_id or data")
            return False
            
        try:
            # Create a unique item_id for this user and event type
            item_id = f"taproot-assets-balances-{user_id}"
            
            # Prepare message with type and data
            message = json.dumps({
                "type": "assets_update",
                "data": assets_data
            })
            
            # Send through core WebSocket manager
            await websocket_manager.send_data(message, item_id)
            logger.debug(f"Sent assets update notification for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending assets update: {str(e)}")
            return False


# Create singleton instance with the name ws_manager to match imports in other files
ws_manager = TaprootAssetsNotifier()
