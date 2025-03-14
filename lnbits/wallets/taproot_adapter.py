"""
Adapter module for Taproot Asset gRPC interfaces.
This centralizes all imports from the generated protobuf files.
"""
import sys
print(f"DEBUG:taproot_adapter:Python version: {sys.version}")
print(f"DEBUG:taproot_adapter:Python path: {sys.path}")
print(f"DEBUG:taproot_adapter:Loading taproot_adapter module")

# Proto message types
print(f"DEBUG:taproot_adapter:Importing taprootassets_pb2")
from lnbits.wallets.tapd_grpc_files import taprootassets_pb2
print(f"DEBUG:taproot_adapter:Importing rfq_pb2")
from lnbits.wallets.tapd_grpc_files.rfqrpc import rfq_pb2
print(f"DEBUG:taproot_adapter:Importing tapchannel_pb2")
from lnbits.wallets.tapd_grpc_files.tapchannelrpc import tapchannel_pb2
print(f"DEBUG:taproot_adapter:Importing lightning_pb2")
from lnbits.wallets.lnd_grpc_files import lightning_pb2
print(f"DEBUG:taproot_adapter:Importing router_pb2")
from lnbits.wallets.lnd_grpc_files.routerrpc import router_pb2

# GRPC services
print(f"DEBUG:taproot_adapter:Importing taprootassets_pb2_grpc")
from lnbits.wallets.tapd_grpc_files import taprootassets_pb2_grpc
print(f"DEBUG:taproot_adapter:Importing rfq_pb2_grpc")
from lnbits.wallets.tapd_grpc_files.rfqrpc import rfq_pb2_grpc
print(f"DEBUG:taproot_adapter:Importing tapchannel_pb2_grpc")
from lnbits.wallets.tapd_grpc_files.tapchannelrpc import tapchannel_pb2_grpc
print(f"DEBUG:taproot_adapter:Importing lightning_pb2_grpc")
from lnbits.wallets.lnd_grpc_files import lightning_pb2_grpc
print(f"DEBUG:taproot_adapter:Importing router_pb2_grpc")
from lnbits.wallets.lnd_grpc_files.routerrpc import router_pb2_grpc

# Create service client factory functions
def create_taprootassets_client(channel):
    """Create a TaprootAssets service client."""
    print(f"DEBUG:taproot_adapter:Creating TaprootAssets client")
    try:
        client = taprootassets_pb2_grpc.TaprootAssetsStub(channel)
        print(f"DEBUG:taproot_adapter:TaprootAssets client created successfully")
        return client
    except Exception as e:
        print(f"DEBUG:taproot_adapter:Error creating TaprootAssets client: {e}")
        raise

def create_rfq_client(channel):
    """Create an RFQ service client."""
    print(f"DEBUG:taproot_adapter:Creating RFQ client")
    try:
        client = rfq_pb2_grpc.RfqStub(channel)
        print(f"DEBUG:taproot_adapter:RFQ client created successfully")
        return client
    except Exception as e:
        print(f"DEBUG:taproot_adapter:Error creating RFQ client: {e}")
        raise

def create_tapchannel_client(channel):
    """Create a TapChannel service client."""
    print(f"DEBUG:taproot_adapter:Creating TapChannel client")
    try:
        client = tapchannel_pb2_grpc.TaprootAssetChannelsStub(channel)
        print(f"DEBUG:taproot_adapter:TapChannel client created successfully")
        return client
    except Exception as e:
        print(f"DEBUG:taproot_adapter:Error creating TapChannel client: {e}")
        raise

def create_lightning_client(channel):
    """Create a Lightning service client."""
    print(f"DEBUG:taproot_adapter:Creating Lightning client")
    try:
        client = lightning_pb2_grpc.LightningStub(channel)
        print(f"DEBUG:taproot_adapter:Lightning client created successfully")
        return client
    except Exception as e:
        print(f"DEBUG:taproot_adapter:Error creating Lightning client: {e}")
        raise

def create_router_client(channel):
    """Create a Router service client."""
    print(f"DEBUG:taproot_adapter:Creating Router client")
    try:
        client = router_pb2_grpc.RouterStub(channel)
        print(f"DEBUG:taproot_adapter:Router client created successfully")
        return client
    except Exception as e:
        print(f"DEBUG:taproot_adapter:Error creating Router client: {e}")
        raise
