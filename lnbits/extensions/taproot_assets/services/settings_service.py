"""
Settings service for Taproot Assets extension.
Handles settings-related business logic.
"""
from typing import Dict, Any, Optional
from http import HTTPStatus
from loguru import logger

from lnbits.core.models import User

from ..models import TaprootSettings
from ..error_utils import log_error, raise_http_exception, ErrorContext
from ..logging_utils import API, SETTINGS
from ..crud import get_or_create_settings, update_settings
from ..tapd_settings import taproot_settings


class SettingsService:
    """
    Service for handling Taproot Assets settings.
    This service encapsulates settings-related business logic.
    """
    
    @staticmethod
    async def get_settings(user: User) -> TaprootSettings:
        """
        Get Taproot Assets extension settings.
        
        Args:
            user: The user requesting the settings
            
        Returns:
            TaprootSettings: The extension settings
            
        Raises:
            HTTPException: If the user is not an admin
        """
        with ErrorContext("get_settings", SETTINGS):
            if not user.admin:
                raise_http_exception(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail="Only admin users can access settings",
                )

            settings = await get_or_create_settings()
            return settings
    
    @staticmethod
    async def update_settings(settings: TaprootSettings, user: User) -> TaprootSettings:
        """
        Update Taproot Assets extension settings.
        
        Args:
            settings: The new settings
            user: The user updating the settings
            
        Returns:
            TaprootSettings: The updated settings
            
        Raises:
            HTTPException: If the user is not an admin
        """
        with ErrorContext("update_settings", SETTINGS):
            if not user.admin:
                raise_http_exception(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail="Only admin users can update settings",
                )

            updated_settings = await update_settings(settings)
            return updated_settings
    
    @staticmethod
    async def get_tapd_settings(user: User) -> Dict[str, Any]:
        """
        Get Taproot daemon settings.
        
        Args:
            user: The user requesting the settings
            
        Returns:
            Dict[str, Any]: The daemon settings
            
        Raises:
            HTTPException: If the user is not an admin
        """
        with ErrorContext("get_tapd_settings", SETTINGS):
            if not user.admin:
                raise_http_exception(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail="Only admin users can view Taproot daemon settings",
                )

            # Convert settings to a dictionary
            settings_dict = {}
            for key in dir(taproot_settings):
                if not key.startswith('_') and not callable(getattr(taproot_settings, key)) and key not in ['extension_dir', 'config_path', 'config']:
                    settings_dict[key] = getattr(taproot_settings, key)

            return settings_dict
    
    @staticmethod
    async def update_tapd_settings(data: Dict[str, Any], user: User) -> Dict[str, Any]:
        """
        Update Taproot daemon settings.
        
        Args:
            data: The new settings
            user: The user updating the settings
            
        Returns:
            Dict[str, Any]: The updated settings
            
        Raises:
            HTTPException: If the user is not an admin
        """
        with ErrorContext("update_tapd_settings", SETTINGS):
            if not user.admin:
                raise_http_exception(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail="Only admin users can update Taproot daemon settings",
                )

            # Update only the settings that were provided
            updated_keys = []
            for key, value in data.items():
                if hasattr(taproot_settings, key) and value is not None:
                    setattr(taproot_settings, key, value)
                    updated_keys.append(key)

            # Save the updated settings
            taproot_settings.save()

            return {
                "success": True,
                "settings": {key: getattr(taproot_settings, key) for key in updated_keys if hasattr(taproot_settings, key)}
            }
