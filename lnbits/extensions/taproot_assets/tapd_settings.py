import os
from typing import Dict, Any
from loguru import logger

# Default cache expiry times
ASSET_CACHE_EXPIRY_SECONDS = 300  # 5 minutes

class TaprootSettings:
    """
    Load Taproot Assets settings from environment variables.
    """
    
    def __init__(self):
        # TAPD connection settings
        self.tapd_host = os.environ.get("TAPD_HOST", None)
        self.tapd_network = os.environ.get("TAPD_NETWORK", "mainnet")  # Keeping default for network
        self.tapd_tls_cert_path = os.environ.get("TAPD_TLS_CERT_PATH", None)
        self.tapd_macaroon_path = os.environ.get("TAPD_MACAROON_PATH", None)
        self.tapd_macaroon_hex = os.environ.get("TAPD_MACAROON_HEX", None)
        
        # LND connection settings
        self.lnd_macaroon_path = os.environ.get("LND_REST_MACAROON", None)
        self.lnd_macaroon_hex = os.environ.get("LND_MACAROON_HEX", None)
        
        # Fee settings
        self.default_sat_fee = int(os.environ.get("TAPD_DEFAULT_SAT_FEE", "1"))  # Keeping default for fee
        
        logger.info("Taproot Assets settings loaded from environment variables")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to a dictionary for API responses."""
        return {
            "tapd_host": self.tapd_host,
            "tapd_network": self.tapd_network,
            "tapd_tls_cert_path": self.tapd_tls_cert_path,
            "tapd_macaroon_path": self.tapd_macaroon_path,
            "tapd_macaroon_hex": self.tapd_macaroon_hex,
            "lnd_macaroon_path": self.lnd_macaroon_path,
            "lnd_macaroon_hex": self.lnd_macaroon_hex,
            "default_sat_fee": self.default_sat_fee
        }

# Create a singleton instance
taproot_settings = TaprootSettings()
