from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class TaprootSettings(BaseModel):
    """Settings for the Taproot Assets extension."""
    tapd_host: str = "lit:10009"
    tapd_network: str = "mainnet"
    tapd_tls_cert_path: str = "/root/.lnd/tls.cert"
    tapd_macaroon_path: str = "/root/.tapd/data/mainnet/admin.macaroon"
    tapd_macaroon_hex: Optional[str] = None
    lnd_macaroon_path: str = "/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon"
    lnd_macaroon_hex: Optional[str] = None
    default_sat_fee: int = 1  # Default satoshi fee for Taproot Asset transfers


class TaprootAsset(BaseModel):
    """Model for a Taproot Asset."""
    id: str
    name: str
    asset_id: str
    type: str
    amount: str
    genesis_point: str
    meta_hash: str
    version: str
    is_spent: bool
    script_key: str
    channel_info: Optional[Dict[str, Any]] = None
    user_id: str
    created_at: datetime
    updated_at: datetime


class TaprootInvoiceRequest(BaseModel):
    """Request model for creating a Taproot Asset invoice."""
    asset_id: str
    amount: int
    memo: Optional[str] = None
    expiry: Optional[int] = None
    peer_pubkey: Optional[str] = None  # Add peer_pubkey parameter for multi-channel support


class TaprootPaymentRequest(BaseModel):
    """Request model for paying a Taproot Asset invoice."""
    payment_request: str
    fee_limit_sats: Optional[int] = 1000  # Default to 1000 sats fee limit
    peer_pubkey: Optional[str] = None  # Add peer_pubkey for multi-channel support


class TaprootInvoice(BaseModel):
    """Model for a Taproot Asset invoice."""
    id: str
    payment_hash: str
    payment_request: str
    asset_id: str
    asset_amount: int
    satoshi_amount: int  # Satoshi amount for protocol requirements (from settings)
    memo: Optional[str] = None
    status: str = "pending"
    user_id: str
    wallet_id: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None


class TaprootPayment(BaseModel):
    """Model for a Taproot Asset payment."""
    id: str
    payment_hash: str
    payment_request: str
    asset_id: str
    asset_amount: int
    fee_sats: int
    memo: Optional[str] = None
    status: str = "completed"
    user_id: str
    wallet_id: str
    created_at: datetime
    preimage: Optional[str] = None


class FeeTransaction(BaseModel):
    """Model for tracking satoshi fee transactions."""
    id: str
    user_id: str
    wallet_id: str
    asset_payment_hash: str
    fee_amount_msat: int
    status: str  # "deducted", "refunded", or "failed"
    created_at: datetime


class AssetBalance(BaseModel):
    """Model for a user's asset balance."""
    id: str
    wallet_id: str
    asset_id: str
    balance: int
    last_payment_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AssetTransaction(BaseModel):
    """Model for an asset transaction."""
    id: str
    wallet_id: str
    asset_id: str
    payment_hash: Optional[str] = None
    amount: int
    fee: int = 0
    memo: Optional[str] = None
    type: str  # 'credit', 'debit'
    created_at: datetime
