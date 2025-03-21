import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

class TaprootSettings:
    """Settings for Taproot Assets extension that were previously in global settings."""
    
    def __init__(self):
        self.extension_dir = Path(os.path.dirname(os.path.realpath(__file__)))
        self.config_path = self.extension_dir / "tapd_config.json"
        
        # Default configuration values
        default_config = {
            "tapd_host": "lit:10009",
            "tapd_network": "signet",
            "tapd_tls_cert_path": "/root/.lnd/tls.cert",
            "tapd_macaroon_path": "/root/.tapd/data/signet/admin.macaroon",
            "tapd_macaroon_hex": "",
            "lnd_macaroon_path": "/root/.lnd/data/chain/bitcoin/signet/admin.macaroon",
            "lnd_macaroon_hex": "",
            "tapd_rfq_price_oracle_address": "use_mock_price_oracle_service_promise_to_not_use_on_mainnet",
            "tapd_rfq_mock_oracle_assets_per_btc": 100000,
            "tapd_rfq_skip_accept_quote_price_check": False
        }
        
        # Load existing configuration or create with defaults
        self.config = self._load_config(default_config)
        
        # Set attributes from config
        for key, value in self.config.items():
            setattr(self, key, value)
    
    def _load_config(self, default_config: Dict[str, Any]) -> Dict[str, Any]:
        """Load configuration from file or create with defaults."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config, using defaults: {e}")
                return default_config
        else:
            # Create config file with defaults
            with open(self.config_path, "w") as f:
                json.dump(default_config, f, indent=2)
            return default_config
    
    def save(self):
        """Save current settings to config file."""
        config = {}
        # Get all attributes that don't start with underscore
        for key in dir(self):
            if not key.startswith('_') and not callable(getattr(self, key)):
                config[key] = getattr(self, key)
        
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

# Create a singleton instance
taproot_settings = TaprootSettings()
