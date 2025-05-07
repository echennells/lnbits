"""
Payment record service for Taproot Assets extension.
Handles payment record-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
from http import HTTPStatus
from loguru import logger

from lnbits.core.models import WalletTypeInfo, User
from lnbits.core.crud import get_user

from ..models import TaprootPayment
from ..error_utils import raise_http_exception
# Import from specific CRUD submodule
from ..crud.payments import get_user_payments, get_fee_transactions


class PaymentRecordService:
    """
    Service for handling Taproot Asset payment records.
    This service encapsulates payment record-related business logic.
    """
    
    @staticmethod
    async def get_user_payments(user_id: str) -> List[TaprootPayment]:
        """
        Get all Taproot Asset payments for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            List[TaprootPayment]: List of payments
            
        Raises:
            HTTPException: If there's an error retrieving payments
        """
        try:
            payments = await get_user_payments(user_id)
            return payments
        except Exception as e:
            logger.error(f"Error retrieving payments: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve payments: {str(e)}",
            )
    
    @staticmethod
    async def get_fee_transactions(wallet: WalletTypeInfo) -> List[Dict[str, Any]]:
        """
        Get fee transactions for a user.
        
        Args:
            wallet: The wallet information
            
        Returns:
            List[Dict[str, Any]]: List of fee transactions
            
        Raises:
            HTTPException: If there's an error retrieving fee transactions
        """
        try:
            # Get user information
            user = await get_user(wallet.wallet.user)
            if not user:
                raise_http_exception(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail="User not found",
                )
                
            # If admin, can view all transactions, otherwise just their own
            if user.admin:
                transactions = await get_fee_transactions()
            else:
                transactions = await get_fee_transactions(user.id)

            return transactions
        except Exception as e:
            logger.error(f"Error retrieving fee transactions: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve fee transactions: {str(e)}",
            )
