"""
Database module for the Taproot Assets extension.
Re-exports all CRUD functions to maintain backward compatibility.
"""

# Re-export the db module
from ..db import db, get_table_name

# Import all functions from the modules
from .assets import create_asset, get_assets, get_asset
from .invoices import (
    create_invoice, get_invoice, get_invoice_by_payment_hash, update_invoice_status,
    get_user_invoices, is_self_payment, is_internal_payment, validate_invoice_for_settlement,
    update_invoice_for_settlement
)
from .payments import (
    create_payment_record, get_user_payments, create_fee_transaction, get_fee_transactions
)
from .balances import (
    get_asset_balance, get_wallet_asset_balances, update_asset_balance
)
from .transactions import (
    record_asset_transaction, get_asset_transactions, record_settlement_transaction,
    process_settlement_transaction
)
