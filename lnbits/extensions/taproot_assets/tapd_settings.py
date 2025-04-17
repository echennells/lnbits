import json
import os
from loguru import logger

class TapdSettingsManager:
    """
    Manager for Taproot Assets daemon settings.
    """

    def __init__(self):
        # Get the extension directory
        self.extension_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Configuration file path
        self.config_path = os.path.join(self.extension_dir, "tapd_config.json")
        
        # Default settings
        self.tapd_host = "lit:10009"
        self.tapd_network = "mainnet"
        self.tapd_tls_cert_path = "/root/.lnd/tls.cert"
        self.tapd_macaroon_path = "/root/.tapd/data/mainnet/admin.macaroon"
        self.tapd_macaroon_hex = None
        self.lnd_macaroon_path = "/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon" 
        self.lnd_macaroon_hex = None
        self.default_sat_fee = 1  # Default to 1 sat fee
        
        # Load settings from config file if it exists
        self.load()

    def load(self):
        """
        Load settings from the config file.
        """
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                    
                    # Load settings from config
                    for key in [
                        "tapd_host", "tapd_network", "tapd_tls_cert_path",
                        "tapd_macaroon_path", "tapd_macaroon_hex",
                        "lnd_macaroon_path", "lnd_macaroon_hex",
                        "default_sat_fee"
                    ]:
                        if key in config:
                            setattr(self, key, config[key])
                    
                    self.config = config
            else:
                self.config = {}
        except Exception as e:
            logger.error(f"Failed to load Taproot Assets daemon config: {str(e)}")
            self.config = {}

    def save(self):
        """
        Save settings to the config file.
        """
        try:
            # Create settings dictionary
            self.config = {
                "tapd_host": self.tapd_host,
                "tapd_network": self.tapd_network,
                "tapd_tls_cert_path": self.tapd_tls_cert_path,
                "tapd_macaroon_path": self.tapd_macaroon_path,
                "tapd_macaroon_hex": self.tapd_macaroon_hex,
                "lnd_macaroon_path": self.lnd_macaroon_path,
                "lnd_macaroon_hex": self.lnd_macaroon_hex,
                "default_sat_fee": self.default_sat_fee
            }
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            # Save to file
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
                
            logger.debug(f"Saved Taproot Assets daemon config to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save Taproot Assets daemon config: {str(e)}")

# Create a singleton instance of the settings manager
taproot_settings = TapdSettingsManager()
