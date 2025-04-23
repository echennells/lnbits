from fastapi import Depends, HTTPException, Request
from lnbits.decorators import check_user_exists, get_key_type
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import User, WalletTypeInfo

async def user_or_wallet_auth(request: Request):
    """
    Custom dependency that allows either cookie-based or API key authentication.
    Returns either a User object (from cookie auth) or a WalletTypeInfo object (from API key auth).
    """
    # First try cookie authentication
    try:
        user = await check_user_exists(request)
        return {"user": user, "wallet": None}
    except HTTPException:
        # If cookie auth fails, try API key authentication
        key = request.headers.get("X-Api-Key")
        if not key:
            raise HTTPException(
                status_code=401, detail="Missing user ID or access token."
            )
        
        key_type = await get_key_type(key)
        if key_type == "invalid":
            raise HTTPException(
                status_code=401, detail="Invalid key."
            )
        
        wallet = await get_wallet(key)
        if not wallet:
            raise HTTPException(
                status_code=404, detail="Wallet not found."
            )
        
        user = await get_user(wallet.user)
        if not user:
            raise HTTPException(
                status_code=404, detail="User not found."
            )
        
        return {"user": user, "wallet": WalletTypeInfo(key_type=key_type, wallet=wallet)}
