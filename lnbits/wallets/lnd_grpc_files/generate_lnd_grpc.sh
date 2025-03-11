#!/bin/bash
# Create a new script in the lnd_grpc_files directory
cd ~/fresh/lnbits/lnbits/wallets/lnd_grpc_files
cat > regenerate_lnd_grpc.sh << 'EOF'
#!/bin/bash
# Generate protobuf files for the LND protos
echo "Generating Python code from lightning.proto..."

# Remove old generated files to start fresh
rm -f lightning_pb2.py lightning_pb2_grpc.py

# Generate new files
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. lightning.proto

# Fix the imports to be relative
sed -i 's/import lightning_pb2/from . import lightning_pb2/' lightning_pb2_grpc.py

# Ensure __init__.py exists
touch __init__.py

echo "Done generating code. Checking for custom_channel_data field..."
grep -n "custom_channel_data" lightning_pb2.py

echo "Script completed"
EOF

# Make it executable
chmod +x regenerate_lnd_grpc.sh

# Run it
./regenerate_lnd_grpc.sh
