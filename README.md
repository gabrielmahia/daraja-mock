# daraja-mock

A small local test double for the Safaricom M-Pesa Daraja API, built on Flask. It lets you exercise OAuth and STK Push flows (and the request shapes of B2C v3, transaction status and account balance; there is no C2B, B2B or reversal endpoint, and those paths return 404) without a Safaricom account, credentials or internet access.

[![CI](https://github.com/gabrielmahia/daraja-mock/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielmahia/daraja-mock/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![License](https://img.shields.io/badge/License-CC%20BY--NC--ND%204.0-lightgrey)](LICENSE)

> **What this is, and is not.** A test double, not a simulator of Safaricom's behaviour, and not affiliated with Safaricom. Only the **STK Push query result** is configurable. B2C, Account Balance and Transaction Status always return an "accepted" response, and **no asynchronous result callbacks are sent**. See [Limits](#limits).

## Install

```bash
pip install daraja-mock    # installs Flask
```

## Quickstart

```python
import requests
from daraja_mock import DarajaMock

mock = DarajaMock()
base_url = mock.run_thread(port=18080)      # non-blocking; returns "http://127.0.0.1:18080"

token = requests.get(f"{base_url}/oauth/v1/generate").json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

push = requests.post(
    f"{base_url}/mpesa/stkpush/v1/processrequest", headers=headers,
    json={"BusinessShortCode": "174379", "Amount": 100, "PhoneNumber": "254712345678",
          "CallBackURL": "https://example.com/callback", "AccountReference": "Order001", "TransactionDesc": "Payment"},
).json()
assert push["ResponseCode"] == "0"

mock.set_stk_result(1032)                   # STK queries now report "cancelled by user"
status = requests.post(f"{base_url}/mpesa/stkpushquery/v1/query", headers=headers,
                       json={"CheckoutRequestID": push["CheckoutRequestID"]}).json()
assert status["ResultCode"] == "1032"
```

## Configuration

| Method | Effect |
|--------|--------|
| `set_stk_result(code)` | The `ResultCode` returned by every STK Push query. Described codes: `0` success, `1` insufficient balance, `1001` and `2001` invalid initiator, `1032` cancelled by user, `1037` timeout. Any other code is returned as `Error <code>`. |
| `reset()` | Restore defaults and clear the request log. |
| `request_log()` | List of recorded requests, each a dict with `method`, `path`, `body` and `ts`. |
| `set_b2c_result(...)`, `set_balance(...)` | **No effect yet** (they warn). The B2C and balance endpoints always accept. |

The STK query endpoint returns the configured `ResultCode` for any `CheckoutRequestID`; it does not look the id up, and it returns a fresh random `CheckoutRequestID` of its own.

## Endpoints

| Endpoint | Method | Behaviour |
|----------|--------|-----------|
| `/oauth/v1/generate` | GET | Returns `access_token` and `expires_in`; credentials are not checked. |
| `/mpesa/stkpush/v1/processrequest` | POST | Accepts the request; `ResponseCode` is `"0"`. |
| `/mpesa/stkpushquery/v1/query` | POST | Returns the configured `ResultCode`. |
| `/mpesa/b2c/v3/paymentrequest` | POST | Always accepted. |
| `/mpesa/transactionstatus/v1/query` | POST | Always accepted. |
| `/mpesa/accountbalance/v1/query` | POST | Always accepted. |
| `/mock/balance-callback` | POST | Receives a balance result if you use it as your callback URL. |
| `/health` | GET | `{"status": "ok", "version": ...}` |

## Standalone server

```bash
python -m daraja_mock                 # http://127.0.0.1:8765
python -m daraja_mock --port 9000
daraja-mock --port 9000               # the same, as an installed command
```

## Use with pesa-cli

[pesa-cli](https://github.com/gabrielmahia/pesa-cli) 1.0.1 and later reads `PESA_BASE_URL`, so its commands can run against this server:

```bash
python -m daraja_mock --port 8765 &
export PESA_BASE_URL=http://127.0.0.1:8765
pesa auth && pesa stk push 0712345678 100
```

`daraja-v3` (the `mpesa-python` SDK) 0.1.2 and later accept `MpesaClient(..., base_url="http://localhost:8765")`, so the SDK can be pointed at this server; its own test suite does exactly that. `base_url` must be `https://`, or `http://` for localhost only.

## Limits

- Credentials, shortcodes, passkeys and callback URLs are not validated.
- No asynchronous result or callback delivery: STK, B2C and balance results that real Daraja posts to your URLs are not sent.
- STK query is stateless (see above). No C2B URL registration endpoint.
- It runs on Flask's development server, in a daemon thread for `run_thread`, in one process.

## Tests

```bash
pip install -e ".[dev]" && python -m pytest
```

The tests also fail if this README names a class, method or endpoint that does not exist, and they run the Quickstart above.

*Part of the [nairobi-stack](https://github.com/gabrielmahia/nairobi-stack) East Africa engineering ecosystem.*
*Maintained by [Gabriel Mahia](https://github.com/gabrielmahia). Kenya × USA.*
