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
    async def notify_invoice_update(user_id: str, invoice_data: Dict[str, Any]):
        """
        Notify about invoice status update.
        """
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
        except Exception as e:
            logger.error(f"Error sending invoice update: {str(e)}")
    
    @staticmethod
    async def notify_payment_update(user_id: str, payment_data: Dict[str, Any]):
        """
        Notify about payment status update.
        """
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
        except Exception as e:
            logger.error(f"Error sending payment update: {str(e)}")
    
    @staticmethod
    async def notify_assets_update(user_id: str, assets_data: List[Dict[str, Any]]):
        """
        Notify about assets balance update.
        """
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
        except Exception as e:
            logger.error(f"Error sending assets update: {str(e)}")


# Create singleton instance with the name ws_manager to match imports in other files
ws_manager = TaprootAssetsNotifier()
