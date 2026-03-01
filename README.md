# daraja-mock

**Local test server for the Safaricom M-Pesa Daraja v3 API. Zero dependencies. No Safaricom account needed.**

[![CI](https://github.com/gabrielmahia/daraja-mock/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielmahia/daraja-mock/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![Tests](https://img.shields.io/badge/tests-32%20passing-brightgreen)](#)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-success)](#)
[![License](https://img.shields.io/badge/License-CC%20BY--NC--ND%204.0-lightgrey)](LICENSE)

Test your M-Pesa integration without hitting Safaricom sandbox. Runs in-process as a context manager
or as a standalone server. Configurable failure scenarios so you can test every edge case your
production system will encounter.

---

## Install

```bash
pip install daraja-mock
```

---

## Usage in pytest

```python
from daraja_mock import DarajaMock, Scenario

def test_stk_push_success():
    mock = DarajaMock()
    with mock.run() as base_url:
        # Point your client at the mock instead of Safaricom
        client = MyMpesaClient(base_url=base_url)
        result = client.stk_push("0712345678", 100, "OrderRef")

    assert result.checkout_request_id == mock.last_stk_checkout_id
    assert mock.calls[0].endpoint == "/mpesa/stkpush/v1/processrequest"
    assert mock.calls[0].body["Amount"] == 100

def test_user_cancels():
    mock = DarajaMock()
    mock.set_scenario(Scenario.USER_CANCELLED)
    with mock.run() as base_url:
        result = client.stk_query(mock.last_stk_checkout_id, base_url=base_url)
    assert result.result_code == 1032
```

---

## Scenarios

| Scenario | Triggers | Result code |
|----------|----------|-------------|
| `SUCCESS` | Default | 0 |
| `USER_CANCELLED` | Customer pressed cancel | 1032 |
| `INSUFFICIENT_FUNDS` | Not enough balance | 1 |
| `TIMED_OUT` | PIN entry timed out | 1037 |
| `WRONG_PIN` | Bad PIN entered | 2001 |
| `SYSTEM_ERROR` | Daraja internal error | 17 / HTTP 500 |
| `AUTH_FAILURE` | Bad consumer key | HTTP 400 on /oauth |

```python
# Apply to all subsequent calls
mock.set_scenario(Scenario.INSUFFICIENT_FUNDS)

# Queue different outcomes for sequential calls
mock.queue_scenarios(Scenario.SUCCESS, Scenario.USER_CANCELLED, Scenario.TIMED_OUT)
```

---

## Endpoints implemented

| Endpoint | Method |
|----------|--------|
| `/oauth/v1/generate` | GET |
| `/mpesa/stkpush/v1/processrequest` | POST |
| `/mpesa/stkpushquery/v1/query` | POST |
| `/mpesa/b2c/v3/paymentrequest` | POST |
| `/mpesa/c2b/v1/registerurl` | POST |
| `/mpesa/accountbalance/v1/query` | POST |

---

## Callback simulation

Build realistic STK Push callback payloads to test your webhook handler:

```python
# Success callback — includes receipt number, amount, phone
payload = mock.build_stk_callback(scenario=Scenario.SUCCESS)

# Failure callbacks
payload = mock.build_stk_callback(scenario=Scenario.USER_CANCELLED)
payload = mock.build_stk_callback(scenario=Scenario.INSUFFICIENT_FUNDS)

# POST it to your FastAPI/Flask/Django handler in tests
response = test_client.post("/api/mpesa/callback", json=payload)
assert response.status_code == 200
```

---

## Standalone server

```bash
daraja-mock               # starts on http://localhost:8765
daraja-mock --port 9000
```

Useful for manual testing with Postman or curl.

---

## Inspecting calls

```python
mock.calls          # list[CallRecord] — every request made
mock.calls[0].endpoint     # "/mpesa/stkpush/v1/processrequest"
mock.calls[0].body         # {"Amount": 100, "PhoneNumber": ...}
mock.calls[0].received_at  # float unix timestamp

mock.last_stk_checkout_id      # CheckoutRequestID from last STK push
mock.last_b2c_conversation_id  # ConversationID from last B2C
mock.last_token                # access_token from last /oauth call
```

---

## Used with mpesa-python

```python
# daraja-mock is the test companion for gabrielmahia/mpesa-python
from daraja_mock import DarajaMock, Scenario
from mpesa import MpesaClient

def test_stk_push_insufficient_funds():
    mock = DarajaMock()
    mock.queue_scenarios(Scenario.SUCCESS, Scenario.INSUFFICIENT_FUNDS)
    with mock.run() as base_url:
        client = MpesaClient(..., base_url=base_url)
        r1 = client.stk_push("0712345678", 100, "Ref1")
        r2 = client.stk_push("0712345678", 9999999, "Ref2")
    assert r1.response_code == "0"
    assert r2.response_code == "0"  # initiation always succeeds
    # failure arrives via callback — use build_stk_callback() to simulate it
```

---

*Maintained by [Gabriel Mahia](https://github.com/gabrielmahia). Kenya × USA.*
*Part of the [East Africa fintech toolkit](https://github.com/gabrielmahia/nairobi-stack).*
