from typing import Optional, Tuple, Dict, Any, cast
import asyncio

from lnbits.utils.cache import cache
from .taproot_wallet import TaprootWalletExtension
from .taproot_node import TaprootAssetsNodeExtension
from ..logging_utils import log_info, log_debug, log_warning, FACTORY, LogContext


class TaprootAssetsFactory:
    """
    Factory class for creating and initializing Taproot Assets wallet and node instances.
    This follows the Core LNbits Pattern where the wallet and node are created separately
    and then connected, rather than having the wallet create the node directly.
    
    This factory also implements a caching mechanism to avoid creating multiple wallet
    instances for the same user and wallet ID.
    """
    # Cache expiry time in seconds
    WALLET_CACHE_EXPIRY = 3600  # 1 hour
    
    @classmethod
    async def create_wallet_and_node(
        cls,
        user_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        host: Optional[str] = None,
        network: Optional[str] = None,
        tls_cert_path: Optional[str] = None,
        macaroon_path: Optional[str] = None,
        ln_macaroon_path: Optional[str] = None,
        ln_macaroon_hex: Optional[str] = None,
        tapd_macaroon_hex: Optional[str] = None,
    ) -> Tuple[TaprootWalletExtension, TaprootAssetsNodeExtension]:
        """
        Create and initialize a TaprootWalletExtension with its associated node.
        
        Args:
            user_id: Optional user ID for the wallet
            wallet_id: Optional wallet ID
            host: Optional host for the Taproot Assets daemon
            network: Optional network (mainnet, testnet, etc.)
            tls_cert_path: Optional path to TLS certificate
            macaroon_path: Optional path to Taproot Assets macaroon
            ln_macaroon_path: Optional path to Lightning macaroon
            ln_macaroon_hex: Optional Lightning macaroon as hex string
            tapd_macaroon_hex: Optional Taproot Assets macaroon as hex string
            
        Returns:
            tuple: (wallet, node) - The initialized wallet and node instances
        """
        # Check if we have valid user_id and wallet_id for caching
        if user_id and wallet_id:
            cache_key = f"taproot:wallet:{user_id}:{wallet_id}"
            
            # Check if we already have a wallet instance for this user and wallet
            wallet = cache.get(cache_key)
            if wallet and wallet.initialized and wallet.node:
                log_debug(FACTORY, f"Using cached wallet instance for user {user_id}, wallet {wallet_id}")
                return wallet, wallet.node
            elif wallet:
                # If the wallet exists but isn't properly initialized, remove it from cache
                log_warning(FACTORY, f"Found uninitialized wallet in cache for {user_id}, {wallet_id}. Recreating.")
                cache.pop(cache_key)
        
        with LogContext(FACTORY, f"Creating wallet and node for user {user_id}, wallet {wallet_id}"):
            # Create wallet
            log_debug(FACTORY, "Creating TaprootWalletExtension instance")
            wallet = TaprootWalletExtension()
            wallet.user = user_id
            wallet.id = wallet_id
            
            # Create node with wallet
            log_debug(FACTORY, "Creating TaprootAssetsNodeExtension instance")
            node = TaprootAssetsNodeExtension(
                wallet=wallet,
                host=host or "",
                network=network or "",
                tls_cert_path=tls_cert_path or "",
                macaroon_path=macaroon_path or "",
                ln_macaroon_path=ln_macaroon_path or "",
                ln_macaroon_hex=ln_macaroon_hex or "",
                tapd_macaroon_hex=tapd_macaroon_hex or ""
            )
            
            # Set the node on the wallet
            log_debug(FACTORY, "Setting node on wallet")
            wallet.node = node
            wallet.initialized = True
            
            # Add to cache if we have a valid user_id and wallet_id
            if user_id and wallet_id:
                cache_key = f"taproot:wallet:{user_id}:{wallet_id}"
                cache.set(cache_key, wallet, expiry=cls.WALLET_CACHE_EXPIRY)
            
            log_info(FACTORY, f"Successfully created wallet and node for user {user_id}, wallet {wallet_id}")
            return wallet, node

    @classmethod
    async def create_wallet(
        cls,
        user_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        **kwargs
    ) -> TaprootWalletExtension:
        """
        Create and initialize just a TaprootWalletExtension.
        This is a convenience method that calls create_wallet_and_node and returns just the wallet.
        
        Args:
            user_id: Optional user ID for the wallet
            wallet_id: Optional wallet ID
            **kwargs: Additional parameters to pass to create_wallet_and_node
            
        Returns:
            TaprootWalletExtension: The initialized wallet instance
        """
        wallet, _ = await cls.create_wallet_and_node(
            user_id=user_id,
            wallet_id=wallet_id,
            **kwargs
        )
        return wallet
