#!/bin/bash
# Generate protobuf files for the core taprootassets proto
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. taprootassets.proto
# Fix the imports to be relative
sed -i 's/import taprootassets_pb2/from . import taprootassets_pb2/' taprootassets_pb2_grpc.py

# Create assetwalletrpc directory if it doesn't exist
mkdir -p assetwalletrpc

# Copy assetwallet.proto from taproot-assets repo if needed
# Uncomment this if you need to copy from another location
# cp ~/taproot-assets/taprpc/assetwalletrpc/assetwallet.proto assetwalletrpc/

# Generate protobuf files for assetwallet
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. assetwalletrpc/assetwallet.proto
# Fix the imports to be relative
sed -i 's/import assetwallet_pb2/from . import assetwallet_pb2/' assetwalletrpc/assetwallet_pb2_grpc.py
sed -i 's/import taprootassets_pb2/from .. import taprootassets_pb2/' assetwalletrpc/assetwallet_pb2.py

# Create __init__.py files if they don't exist
touch __init__.py
touch assetwalletrpc/__init__.py
