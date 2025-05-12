"""
Asset utilities for Taproot Assets extension.
Provides consistent asset handling patterns across the codebase.
"""
from typing import Optional
from .logging_utils import log_info, log_debug, PAYMENT

def resolve_asset_id(client_asset_id: Optional[str], invoice_asset_id: Optional[str]) -> Optional[str]:
    """
    Resolve which asset ID to use based on consistent precedence rules:
    1. Use client-provided asset_id if available
    2. Fall back to invoice asset_id if available
    3. Return None if neither is available
    
    Args:
        client_asset_id: Asset ID provided by the client (e.g., in payment request)
        invoice_asset_id: Asset ID from the invoice
        
    Returns:
        str: The resolved asset ID or None if no valid asset ID is available
    """
    if client_asset_id:
        log_info(PAYMENT, f"Using client-provided asset_id={client_asset_id}")
        return client_asset_id
    
    if invoice_asset_id:
        log_info(PAYMENT, f"Using invoice asset_id={invoice_asset_id}")
        return invoice_asset_id
    
    log_debug(PAYMENT, "No asset ID available from client or invoice")
    return None
