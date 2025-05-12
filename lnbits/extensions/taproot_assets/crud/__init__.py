"""
Re-exports for CRUD operations in the Taproot Assets extension.
"""
from .invoices import (
    create_invoice, get_invoice, get_invoice_by_payment_hash,
    update_invoice_status, get_user_invoices, validate_invoice_for_settlement,
    update_invoice_for_settlement
)
from .payments import (
    create_payment_record, get_user_payments
)
from .invoices import (
    is_internal_payment, is_self_payment
)
from .assets import (
    get_assets, create_asset
)

# Import and re-export the TransactionService methods
from ..services.transaction_service import TransactionService

# Transaction operations
record_asset_transaction = TransactionService.record_transaction
get_asset_transactions = TransactionService.get_asset_transactions

# Balance operations
get_asset_balance = TransactionService.get_asset_balance
get_wallet_asset_balances = TransactionService.get_wallet_asset_balances

# For backward compatibility in function signatures
async def update_asset_balance(wallet_id, asset_id, amount_change, payment_hash=None, conn=None):
    """
    Update asset balance without creating a transaction record.
    """
    tx_type = "credit" if amount_change > 0 else "debit"
    amount = abs(amount_change)
    
    _, _, balance = await TransactionService.record_transaction(
        wallet_id=wallet_id,
        asset_id=asset_id,
        amount=amount,
        tx_type=tx_type,
        payment_hash=payment_hash,
        create_tx_record=False,
        conn=conn
    )
    
    return balance
