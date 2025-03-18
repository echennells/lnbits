import asyncio
from loguru import logger
from lnbits.tasks import register_invoice_listener
from lnbits.core.models import Payment

from .crud import update_invoice_status, get_invoice_by_payment_hash

async def wait_for_paid_invoices():
    """
    Background task that waits for invoice payment notifications.
    This function registers with the LNBits core invoice listener system
    to receive notifications when invoices are paid.
    """
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_taproot_assets")

    logger.info("Taproot Assets payment listener started")
    
    while True:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)

async def on_invoice_paid(payment: Payment):
    """
    Process a paid invoice notification.
    
    This function is called when an invoice is detected as paid. It:
    1. Checks if the payment is for a Taproot Asset
    2. Updates the corresponding invoice status in our database
    
    Args:
        payment: The Payment object from LNBits core
    """
    # Check if this is a Taproot Asset payment by looking at the payment's extra data
    if not payment.extra or payment.extra.get("type") != "taproot_asset":
        return

    logger.info(f"Taproot Asset payment received: {payment.payment_hash}")
    
    # Get our internal invoice record using the payment hash
    invoice = await get_invoice_by_payment_hash(payment.payment_hash)
    if not invoice:
        logger.error(f"Payment received but no invoice found for hash {payment.payment_hash}")
        return
    
    # Update our invoice status to paid
    if invoice.status != "paid":  # Only update if not already marked as paid
        logger.info(f"Updating Taproot Asset invoice {invoice.id} status to paid")
        await update_invoice_status(invoice.id, "paid")
        logger.info(f"Taproot Asset invoice {invoice.id} marked as paid")
    else:
        logger.info(f"Taproot Asset invoice {invoice.id} already marked as paid, skipping")
    
    # Additional operations on payment success could be added here:
    # - Notify users through websockets
    # - Update asset balances
    # - Call webhooks
