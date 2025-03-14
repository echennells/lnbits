#!/usr/bin/env python3
"""
Script to check RFQ offers for a specific asset.
"""
import asyncio
import sys
import os
import grpc
import grpc.aio
import json
from typing import Dict, Any, List

# Add the parent directory to the path so we can import from lnbits
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lnbits.settings import settings
from lnbits.wallets.taproot_adapter import (
    rfq_pb2,
    rfq_pb2_grpc,
    tapchannel_pb2,
    tapchannel_pb2_grpc,
    lightning_pb2,
    create_tapchannel_client
)

async def check_rfq_offers(asset_id: str = None):
    """Check RFQ offers for a specific asset."""
    print(f"Checking RFQ offers for asset: {asset_id}")
    
    # Setup gRPC credentials
    try:
        with open(settings.tapd_tls_cert_path, 'rb') as f:
            cert = f.read()
    except Exception as e:
        print(f"Failed to read TLS cert: {e}")
        return
    
    # Get macaroon
    if settings.tapd_macaroon_hex:
        macaroon = settings.tapd_macaroon_hex
    else:
        try:
            with open(settings.tapd_macaroon_path, 'rb') as f:
                macaroon = f.read().hex()
        except Exception as e:
            print(f"Failed to read macaroon: {e}")
            return
    
    # Setup gRPC auth
    credentials = grpc.ssl_channel_credentials(cert)
    auth_creds = grpc.metadata_call_credentials(
        lambda context, callback: callback([("macaroon", macaroon)], None)
    )
    combined_creds = grpc.composite_channel_credentials(
        credentials, auth_creds
    )
    
    # Create channel and clients
    channel = grpc.aio.secure_channel(settings.tapd_host, combined_creds)
    rfq_client = rfq_pb2_grpc.RfqStub(channel)
    tapchannel_client = create_tapchannel_client(channel)
    
    try:
        # Query peer accepted quotes
        print("Querying peer accepted quotes...")
        rfq_request = rfq_pb2.QueryPeerAcceptedQuotesRequest()
        rfq_response = await rfq_client.QueryPeerAcceptedQuotes(rfq_request, timeout=10)
        print(f"Found {len(rfq_response.buy_quotes)} buy quotes and {len(rfq_response.sell_quotes)} sell quotes")
        
        # Log buy quotes
        for i, quote in enumerate(rfq_response.buy_quotes):
            print(f"Buy Quote {i+1}:")
            print(f"  Peer: {quote.peer}")
            print(f"  SCID: {quote.scid}")
            print(f"  Asset Max Amount: {quote.asset_max_amount}")
            if hasattr(quote, 'ask_asset_rate'):
                print(f"  Ask Asset Rate: {quote.ask_asset_rate.coefficient} (scale: {quote.ask_asset_rate.scale})")
            
            # Check if this quote is for the specified asset
            if asset_id and hasattr(quote, 'asset_id'):
                quote_asset_id = quote.asset_id.hex() if isinstance(quote.asset_id, bytes) else quote.asset_id
                if quote_asset_id == asset_id:
                    print(f"  This quote is for the specified asset: {asset_id}")
        
        # If no asset_id was specified or no matching quotes were found, try to create an invoice
        if asset_id:
            print(f"\nTrying to create an invoice for asset: {asset_id}")
            
            # Convert asset_id from hex to bytes if needed
            asset_id_bytes = bytes.fromhex(asset_id) if isinstance(asset_id, str) else asset_id
            
            # Create a standard invoice for the invoice_request field
            invoice = lightning_pb2.Invoice(
                memo="Test Asset Transfer",
                value=0,  # The value will be determined by the RFQ process
                private=True
            )
            
            # Create the AddInvoiceRequest
            request = tapchannel_pb2.AddInvoiceRequest(
                asset_id=asset_id_bytes,
                asset_amount=10,  # Small test amount
                invoice_request=invoice
            )
            
            # Call the TaprootAssetChannels AddInvoice method
            print("Calling TaprootAssetChannels.AddInvoice...")
            try:
                response = await tapchannel_client.AddInvoice(request, timeout=30)
                
                # Debug response
                print(f"AddInvoice response type: {type(response)}")
                print(f"AddInvoice response attributes: {dir(response)}")
                
                # Check if we got an accepted_buy_quote
                if hasattr(response, 'accepted_buy_quote') and response.accepted_buy_quote:
                    print("\nGot accepted_buy_quote:")
                    print(f"  Peer: {response.accepted_buy_quote.peer}")
                    print(f"  ID: {response.accepted_buy_quote.id}")
                    print(f"  SCID: {response.accepted_buy_quote.scid}")
                    print(f"  Asset Max Amount: {response.accepted_buy_quote.asset_max_amount}")
                    if hasattr(response.accepted_buy_quote, 'ask_asset_rate'):
                        print(f"  Ask Asset Rate: {response.accepted_buy_quote.ask_asset_rate.coefficient} (scale: {response.accepted_buy_quote.ask_asset_rate.scale})")
                else:
                    print("\nNo accepted_buy_quote in the response")
                
                # Check invoice_result
                if hasattr(response, 'invoice_result'):
                    print("\nGot invoice_result:")
                    print(f"  Payment Hash: {response.invoice_result.r_hash.hex() if isinstance(response.invoice_result.r_hash, bytes) else response.invoice_result.r_hash}")
                    print(f"  Payment Request: {response.invoice_result.payment_request}")
                else:
                    print("\nNo invoice_result in the response")
                
            except Exception as e:
                print(f"Error creating invoice: {e}")
    
    except Exception as e:
        print(f"Error querying RFQ service: {e}")
    finally:
        await channel.close()

if __name__ == "__main__":
    asset_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(check_rfq_offers(asset_id))
