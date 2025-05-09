"""
Invoice-related CRUD operations for Taproot Assets extension.
"""
from typing import List, Optional, Tuple
from datetime import datetime, timedelta

from lnbits.helpers import urlsafe_short_hash

from ..models import TaprootInvoice
from ..db import db, get_table_name
from ..db_utils import with_transaction
from .utils import get_record_by_id, get_record_by_field, get_records_by_field

@with_transaction
async def create_invoice(
    asset_id: str,
    asset_amount: int,
    satoshi_amount: int,
    payment_hash: str,
    payment_request: str,
    user_id: str,
    wallet_id: str,
    description: Optional[str] = None,
    expiry: Optional[int] = None,
    conn=None
) -> TaprootInvoice:
    """
    Create a new Taproot Asset invoice.
    
    Args:
        asset_id: The ID of the asset being invoiced
        asset_amount: The amount of the asset being invoiced
        satoshi_amount: The satoshi amount for protocol requirements
        payment_hash: The payment hash for the invoice
        payment_request: The payment request string
        user_id: The ID of the user creating the invoice
        wallet_id: The ID of the wallet for the invoice
        description: Optional description for the invoice
        expiry: Optional expiry time in seconds
        conn: Optional database connection to reuse
        
    Returns:
        TaprootInvoice: The created invoice
    """
    invoice_id = urlsafe_short_hash()
    now = datetime.now()
    expires_at = now + timedelta(seconds=expiry) if expiry else None

    # Create invoice model
    invoice = TaprootInvoice(
        id=invoice_id,
        payment_hash=payment_hash,
        payment_request=payment_request,
        asset_id=asset_id,
        asset_amount=asset_amount,
        satoshi_amount=satoshi_amount,
        description=description,
        status="pending",
        user_id=user_id,
        wallet_id=wallet_id,
        created_at=now,
        expires_at=expires_at,
        paid_at=None
    )
    
    # Insert using standardized method
    await conn.insert(get_table_name("invoices"), invoice)
    
    return invoice


async def get_invoice(invoice_id: str, conn=None) -> Optional[TaprootInvoice]:
    """
    Get a specific Taproot Asset invoice by ID.
    
    Args:
        invoice_id: The ID of the invoice to get
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The invoice if found, None otherwise
    """
    return await get_record_by_id("invoices", invoice_id, TaprootInvoice, conn)


async def get_invoice_by_payment_hash(payment_hash: str, conn=None) -> Optional[TaprootInvoice]:
    """
    Get a specific Taproot Asset invoice by payment hash.
    
    Args:
        payment_hash: The payment hash to look up
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The invoice if found, None otherwise
    """
    return await get_record_by_field("invoices", "payment_hash", payment_hash, TaprootInvoice, conn=conn)


@with_transaction
async def update_invoice_status(invoice_id: str, status: str, conn=None) -> Optional[TaprootInvoice]:
    """
    Update the status of a Taproot Asset invoice.
    
    Args:
        invoice_id: The ID of the invoice to update
        status: The new status for the invoice
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The updated invoice if found, None otherwise
    """
    invoice = await get_invoice(invoice_id, conn)
    if not invoice:
        return None
        
    now = datetime.now()
    invoice.status = status
    
    # Set paid_at timestamp if status is changing to paid
    if status == "paid":
        invoice.paid_at = now
    
    # Update the invoice in the database using standardized method
    await conn.update(
        get_table_name("invoices"),
        invoice,
        "WHERE id = :id"
    )
    
    # Return the updated invoice
    return await get_invoice(invoice_id, conn)


async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
    """
    Get all Taproot Asset invoices for a user.
    
    Args:
        user_id: The ID of the user to get invoices for
        
    Returns:
        List[TaprootInvoice]: List of invoices for the user
    """
    return await get_records_by_field("invoices", "user_id", user_id, TaprootInvoice)


# Payment detection functions
async def is_self_payment(payment_hash: str, user_id: str) -> bool:
    """
    Determine if a payment hash belongs to an invoice created by the same user.
    
    This function checks if the invoice associated with the payment hash was
    created by the user who is trying to pay it, which indicates a self-payment
    (user paying themselves).
    
    Args:
        payment_hash: The payment hash to check
        user_id: The ID of the current user
        
    Returns:
        bool: True if this is a self-payment (same user), False otherwise
    """
    invoice = await get_invoice_by_payment_hash(payment_hash)
    return invoice is not None and invoice.user_id == user_id


async def is_internal_payment(payment_hash: str) -> bool:
    """
    Determine if a payment hash belongs to an invoice created by any user on the same node.
    
    This function checks if the invoice associated with the payment hash exists in
    the local database, which means it was created by some user on this LNbits instance.
    This helps identify payments that can be processed internally without using the
    Lightning Network.
    
    Args:
        payment_hash: The payment hash to check
        
    Returns:
        bool: True if this is an internal payment (any user on same node), False otherwise
    """
    invoice = await get_invoice_by_payment_hash(payment_hash)
    return invoice is not None


@with_transaction
async def validate_invoice_for_settlement(payment_hash: str, conn=None) -> Tuple[bool, Optional[TaprootInvoice], Optional[str]]:
    """
    Validate if an invoice can be settled.
    
    Args:
        payment_hash: The payment hash to check
        conn: Optional database connection to reuse
        
    Returns:
        Tuple containing:
        - success (bool): Whether the invoice is valid for settlement
        - invoice (Optional[TaprootInvoice]): The invoice if found
        - error_message (Optional[str]): Error message if validation fails
    """
    # Step 1: Check if invoice exists
    invoice = await get_invoice_by_payment_hash(payment_hash, conn)
    if not invoice:
        return False, None, "Invoice not found"
    
    # Step 2: Check if already paid
    if invoice.status == "paid":
        return False, invoice, "Invoice already paid"
    
    # Step 3: Check if expired
    now = datetime.now()
    if invoice.expires_at and invoice.expires_at < now:
        return False, invoice, "Invoice expired"
    
    # All validations passed
    return True, invoice, None


@with_transaction
async def update_invoice_for_settlement(invoice: TaprootInvoice, conn=None) -> Optional[TaprootInvoice]:
    """
    Update an invoice to paid status for settlement.
    
    Args:
        invoice: The invoice to update
        conn: Optional database connection to reuse
        
    Returns:
        Optional[TaprootInvoice]: The updated invoice or None if update failed
    """
    from loguru import logger
    try:
        return await update_invoice_status(invoice.id, "paid", conn)
    except Exception as e:
        logger.error(f"Failed to update invoice status: {str(e)}")
        return None
