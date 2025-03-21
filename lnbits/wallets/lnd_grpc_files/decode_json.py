import lightning_pb2
import lightning_pb2_grpc
import grpc
import json

with open('/root/.lnd/tls.cert', 'rb') as f:
    creds = grpc.ssl_channel_credentials(f.read())
with open('/root/.lnd/data/chain/bitcoin/signet/admin.macaroon', 'rb') as f:
    macaroon = f.read()
metadata = [('macaroon', macaroon.hex())]
channel = grpc.secure_channel('lit:10009', creds)
stub = lightning_pb2_grpc.LightningStub(channel)
resp = stub.ListChannels(lightning_pb2.ListChannelsRequest(), metadata=metadata)
for ch in resp.channels:
    if ch.custom_channel_data:
        try:
            data = json.loads(ch.custom_channel_data.decode('utf-8'))
            print(f"Chan ID: {ch.chan_id}, Decoded: {json.dumps(data, indent=2)}")
        except Exception as e:
            print(f"Chan ID: {ch.chan_id}, Raw: {repr(ch.custom_channel_data)}, Error: {e}")
    else:
        print(f"Chan ID: {ch.chan_id}, Custom Data: empty")
