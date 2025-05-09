"""
Database module for the Taproot Assets extension.
Provides access to all CRUD operations.
"""
from typing import Dict, Any, List, Optional, Tuple

# Re-export the db module
from ..db import db, get_table_name

# Import and re-export all functions from the modules
from .assets import create_asset, get_assets
from .invoices import (
    create_invoice, get_invoice, get_invoice_by_payment_hash, update_invoice_status,
    get_user_invoices, is_self_payment, is_internal_payment, validate_invoice_for_settlement,
    update_invoice_for_settlement
)
from .payments import (
    create_payment_record, get_user_payments
)
from .balances import (
    get_asset_balance, get_wallet_asset_balances, update_asset_balance
)
from .transactions import (
    record_asset_transaction, get_asset_transactions, record_settlement_transaction,
    process_settlement_transaction
)

# Define types for settlement response
SettlementResponse = Dict[str, Any]

# Define the public API
__all__ = [
    # Type definitions
    "SettlementResponse",
    
    # DB utilities
    "db", "get_table_name",
    
    # Assets
    "create_asset", "get_assets",
    
    # Invoices
    "create_invoice", "get_invoice", "get_invoice_by_payment_hash", 
    "update_invoice_status", "get_user_invoices", "is_self_payment", 
    "is_internal_payment", "validate_invoice_for_settlement",
    "update_invoice_for_settlement",
    
    # Payments
    "create_payment_record", "get_user_payments",
    
    # Balances
    "get_asset_balance", "get_wallet_asset_balances", "update_asset_balance",
    
    # Transactions
    "record_asset_transaction", "get_asset_transactions", 
    "record_settlement_transaction", "process_settlement_transaction"
]
