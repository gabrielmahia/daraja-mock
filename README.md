# daraja-mock

**Local test server for the Safaricom M-Pesa Daraja v3 API.**

[![CI](https://github.com/gabrielmahia/daraja-mock/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielmahia/daraja-mock/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![Tests](https://img.shields.io/badge/tests-37%20passing-brightgreen)](#)
[![Zero deps](https://img.shields.io/badge/dependencies-zero-brightgreen)](#)
[![License](https://img.shields.io/badge/License-CC%20BY--NC--ND%204.0-lightgrey)](LICENSE)

Test your M-Pesa integration without a Safaricom account, sandbox credentials,
or internet connection. Configure scenarios to simulate user cancellation,
insufficient funds, timeouts, and more — all from a single in-process server.

---

## Install

```bash
pip install daraja-mock
```

---

## Quickstart

```python
from daraja_mock import DarajaMock, Scenario

mock = DarajaMock()

def test_stk_push_success():
    with mock.run() as base_url:
        # Point your MpesaClient at base_url instead of api.safaricom.co.ke
        response = requests.post(
            f"{base_url}/mpesa/stkpush/v1/processrequest",
            json={
                "BusinessShortCode": "174379",
                "Amount": 100,
                "PhoneNumber": "254712345678",
                "CallBackURL": "https://yourapp.com/callback",
                "AccountReference": "Order001",
                "TransactionDesc": "Payment",
            }
        )
    assert response.json()["ResponseCode"] == "0"
    assert mock.last_stk_checkout_id  # store this to query status later

def test_stk_push_user_cancels():
    # STK initiated OK, but user cancels on phone
    mock.queue_scenarios(Scenario.SUCCESS, Scenario.USER_CANCELLED)

    with mock.run() as base_url:
        init = requests.post(f"{base_url}/mpesa/stkpush/v1/processrequest", json={"Amount": 100})
        status = requests.post(f"{base_url}/mpesa/stkpushquery/v1/query", json={
            "CheckoutRequestID": init.json()["CheckoutRequestID"]
        })

    assert status.json()["ResultCode"] == "1032"  # user cancelled
```

---

## Scenarios

| Scenario | ResultCode | Use for |
|----------|-----------|---------|
| `SUCCESS` | 0 | Happy path |
| `USER_CANCELLED` | 1032 | User dismissed STK prompt |
| `INSUFFICIENT_FUNDS` | 1 | Balance too low |
| `TIMED_OUT` | 1037 | User did not respond in time |
| `WRONG_PIN` | 2001 | Wrong M-Pesa PIN entered |
| `SYSTEM_ERROR` | 17 | Safaricom internal error |
| `AUTH_FAILURE` | — | OAuth returns HTTP 400 |

```python
# Single scenario — all calls use this
mock.set_scenario(Scenario.INSUFFICIENT_FUNDS)

# Queue — each call consumes one, then falls back to set_scenario
mock.queue_scenarios(Scenario.SUCCESS, Scenario.USER_CANCELLED, Scenario.TIMED_OUT)
```

---

## Endpoints implemented

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/oauth/v1/generate` | GET | Returns `access_token` |
| `/mpesa/stkpush/v1/processrequest` | POST | STK Push initiation |
| `/mpesa/stkpushquery/v1/query` | POST | Poll STK status |
| `/mpesa/b2c/v3/paymentrequest` | POST | B2C disbursement |
| `/mpesa/c2b/v1/registerurl` | POST | C2B URL registration |
| `/mpesa/accountbalance/v1/query` | POST | Balance enquiry |

---

## Callback simulation

For webhook-based flows, build a realistic callback payload and POST it to your handler:

```python
# Simulate Safaricom posting to your callback URL
payload = mock.build_stk_callback(
    checkout_request_id="ws_CO_123",
    scenario=Scenario.USER_CANCELLED,
)

# POST to your FastAPI/Flask/Django handler
response = test_client.post("/mpesa/stk/callback", json=payload)
assert response.status_code == 200
```

---

## Inspect calls

```python
with mock.run() as base_url:
    # ... make calls ...
    pass

# After the context
assert len(mock.calls) == 2
assert mock.calls[0].endpoint == "/oauth/v1/generate"
assert mock.calls[1].body["Amount"] == 100
```

---

## Standalone server

```bash
# Default port 8765
python -m daraja_mock

# Custom port
python -m daraja_mock --port 9000
```

Then point any HTTP client (Postman, curl, your app) at `http://localhost:8765`.

---

## Use with mpesa-python

```python
import pytest
from daraja_mock import DarajaMock, Scenario
from mpesa import MpesaClient  # github.com/gabrielmahia/mpesa-python

@pytest.fixture
def mpesa_client():
    mock = DarajaMock()
    with mock.run() as base_url:
        client = MpesaClient(
            consumer_key="test_key",
            consumer_secret="test_secret",
            shortcode="174379",
            passkey="test_passkey",
            base_url=base_url,
        )
        yield client, mock

def test_full_stk_flow(mpesa_client):
    client, mock = mpesa_client
    result = client.stk_push("0712345678", 100, "Order001")
    assert result.checkout_request_id == mock.last_stk_checkout_id
```

---

## Design decisions

**No external dependencies.** The server runs on Python's stdlib `HTTPServer`. No FastAPI, no httpx, no pytest-asyncio. This means it works in any test environment without dependency conflicts.

**Thread-safe context manager.** Each `mock.run()` starts a server in a daemon thread and tears it down cleanly on exit. Multiple mocks can run concurrently on different ports.

**Queue-based scenarios.** Real M-Pesa flows have two steps (initiate + query). `queue_scenarios` lets you specify each step independently: `SUCCESS` initiation followed by `USER_CANCELLED` status.

---

*Part of the [nairobi-stack](https://github.com/gabrielmahia/nairobi-stack) East Africa engineering ecosystem.*
*Maintained by [Gabriel Mahia](https://github.com/gabrielmahia). Kenya × USA.*
