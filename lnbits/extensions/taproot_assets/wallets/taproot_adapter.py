"""
Adapter module for Taproot Asset gRPC interfaces.
This centralizes all imports from the generated protobuf files.
"""
from loguru import logger

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
from lnbits.wallets.lnd_grpc_files import lightning_pb2_grpc
from lnbits.wallets.lnd_grpc_files.routerrpc import router_pb2_grpc

# Create service client factory functions
def create_taprootassets_client(channel):
    """Create a TaprootAssets service client."""
    try:
        return taprootassets_pb2_grpc.TaprootAssetsStub(channel)
    except Exception as e:
        logger.error(f"Error creating TaprootAssets client: {e}")
        raise

def create_tapchannel_client(channel):
    """Create a TapChannel service client."""
    try:
        return tapchannel_pb2_grpc.TaprootAssetChannelsStub(channel)
    except Exception as e:
        logger.error(f"Error creating TapChannel client: {e}")
        raise

def create_lightning_client(channel):
    """Create a Lightning service client."""
    try:
        return lightning_pb2_grpc.LightningStub(channel)
    except Exception as e:
        logger.error(f"Error creating Lightning client: {e}")
        raise
