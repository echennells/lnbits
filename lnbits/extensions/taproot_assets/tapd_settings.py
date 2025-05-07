import os
from typing import Dict, Any
from loguru import logger

class TaprootSettings:
    """
    Load Taproot Assets settings from environment variables.
    """
    
    def __init__(self):
        # TAPD connection settings
        self.tapd_host = os.environ.get("TAPROOT_TAPD_HOST", "lit:10009")
        self.tapd_network = os.environ.get("TAPROOT_NETWORK", "mainnet")
        self.tapd_tls_cert_path = os.environ.get("TAPROOT_TLS_CERT_PATH", "/root/.lnd/tls.cert")
        self.tapd_macaroon_path = os.environ.get("TAPROOT_MACAROON_PATH", "/root/.tapd/data/mainnet/admin.macaroon")
        self.tapd_macaroon_hex = os.environ.get("TAPROOT_MACAROON_HEX", None)
        
        # LND connection settings
        self.lnd_macaroon_path = os.environ.get("TAPROOT_LND_MACAROON_PATH", "/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon")
        self.lnd_macaroon_hex = os.environ.get("TAPROOT_LND_MACAROON_HEX", None)
        
        # Fee settings
        self.default_sat_fee = int(os.environ.get("TAPROOT_DEFAULT_SAT_FEE", "1"))
        
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
