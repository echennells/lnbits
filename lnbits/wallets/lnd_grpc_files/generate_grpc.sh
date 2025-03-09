#!/bin/bash
# Generate protobuf files for lightning.proto
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. lightning.proto
# Fix imports to be relative
sed -i 's/import lightning_pb2/from . import lightning_pb2/' lightning_pb2_grpc.py
# Create __init__.py if it doesn't exist
touch __init__.py
