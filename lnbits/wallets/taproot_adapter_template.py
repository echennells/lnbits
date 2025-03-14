"""
Adapter module for Taproot Asset gRPC interfaces.
This centralizes all imports from the generated protobuf files.

To use this adapter in the LNBits application:
1. Rename this file to taproot_adapter.py
2. Place it in the lnbits/wallets/ directory
3. Import from this module rather than directly from the protobuf files
"""

# Proto message types
from lnbits.wallets.tapd_grpc_files import taprootassets_pb2
from lnbits.wallets.tapd_grpc_files.rfqrpc import rfq_pb2
from lnbits.wallets.tapd_grpc_files.tapchannelrpc import tapchannel_pb2
from lnbits.wallets.lnd_grpc_files import lightning_pb2
from lnbits.wallets.lnd_grpc_files.routerrpc import router_pb2

# GRPC services
from lnbits.wallets.tapd_grpc_files import taprootassets_pb2_grpc
from lnbits.wallets.tapd_grpc_files.rfqrpc import rfq_pb2_grpc
from lnbits.wallets.tapd_grpc_files.tapchannelrpc import tapchannel_pb2_grpc

# Create service client factory functions
def create_taprootassets_client(channel):
    """Create a TaprootAssets service client."""
    return taprootassets_pb2_grpc.TaprootAssetsStub(channel)

def create_rfq_client(channel):
    """Create an RFQ service client."""
    return rfq_pb2_grpc.RfqStub(channel)

def create_tapchannel_client(channel):
    """Create a TapChannel service client."""
    return tapchannel_pb2_grpc.TapchannelStub(channel)
