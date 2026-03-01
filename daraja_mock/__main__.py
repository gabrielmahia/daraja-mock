"""Run daraja-mock as a standalone server: python -m daraja_mock"""
import argparse
from daraja_mock import DarajaMock

parser = argparse.ArgumentParser(description="daraja-mock: local Daraja v3 test server")
parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
args = parser.parse_args()

mock = DarajaMock(port=args.port)
print(f"daraja-mock running on http://localhost:{args.port}")
print("Endpoints: /oauth/v1/generate  /mpesa/stkpush/v1/processrequest  /mpesa/stkpushquery/v1/query")
print("           /mpesa/b2c/v3/paymentrequest  /mpesa/c2b/v1/registerurl  /mpesa/accountbalance/v1/query")
print("Press Ctrl+C to stop.")
with mock.run() as url:
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped.")
