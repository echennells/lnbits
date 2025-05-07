"""
Database module for the Taproot Assets extension.
Re-exports all CRUD functions from submodules to maintain backward compatibility.
"""
from typing import Dict, Any, List, Optional, Tuple

# Re-export the db module
from .db import db, get_table_name

# Re-export all functions from the submodules
from .crud.assets import create_asset, get_assets, get_asset
from .crud.invoices import (
    create_invoice, get_invoice, get_invoice_by_payment_hash, update_invoice_status,
    get_user_invoices, is_self_payment, is_internal_payment, validate_invoice_for_settlement,
    update_invoice_for_settlement
)
from .crud.payments import (
    create_payment_record, get_user_payments, create_fee_transaction, get_fee_transactions
)
from .crud.balances import (
    get_asset_balance, get_wallet_asset_balances, update_asset_balance
)
from .crud.transactions import (
    record_asset_transaction, get_asset_transactions, record_settlement_transaction,
    process_settlement_transaction
)

# Define types for settlement response
SettlementResponse = Dict[str, Any]
