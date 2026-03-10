"""Tests for DarajaMock server."""
import requests
import pytest
from daraja_mock import DarajaMock

@pytest.fixture(scope="module")
def mock():
    m = DarajaMock()
    url = m.run_thread(port=18081)
    yield m, url

def test_health(mock):
    m, url = mock
    r = requests.get(f"{url}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_oauth_token(mock):
    m, url = mock
    r = requests.get(f"{url}/oauth/v1/generate")
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["access_token"].startswith("mock_token_")

def test_stk_push(mock):
    m, url = mock
    r = requests.post(f"{url}/mpesa/stkpush/v1/processrequest", json={
        "BusinessShortCode": "174379",
        "Amount": 100,
        "PhoneNumber": "254712345678",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ResponseCode"] == "0"
    assert "CheckoutRequestID" in data

def test_stk_query_success(mock):
    m, url = mock
    m.set_stk_result(0)
    r = requests.post(f"{url}/mpesa/stkpushquery/v1/query", json={
        "CheckoutRequestID": "ws_CO_test123"
    })
    assert r.json()["ResultCode"] == "0"

def test_stk_query_cancelled(mock):
    m, url = mock
    m.set_stk_result(1032)
    r = requests.post(f"{url}/mpesa/stkpushquery/v1/query", json={
        "CheckoutRequestID": "ws_CO_test456"
    })
    assert r.json()["ResultCode"] == "1032"
    assert "cancelled" in r.json()["ResultDesc"].lower()

def test_b2c_success(mock):
    m, url = mock
    m.set_b2c_result("success")
    r = requests.post(f"{url}/mpesa/b2c/v3/paymentrequest", json={
        "Amount": 500, "PartyB": "254712345678"
    })
    assert r.json()["ResponseCode"] == "0"

def test_b2c_insufficient_funds(mock):
    m, url = mock
    m.set_b2c_result("insufficient_funds")
    r = requests.post(f"{url}/mpesa/b2c/v3/paymentrequest", json={})
    assert r.status_code == 200  # Daraja always returns 200

def test_request_log(mock):
    m, url = mock
    m.reset()
    requests.get(f"{url}/health")
    requests.post(f"{url}/mpesa/stkpush/v1/processrequest", json={"test": 1})
    log = m.request_log()
    assert len(log) == 2
    assert log[0]["path"] == "/health"
    assert log[1]["path"] == "/mpesa/stkpush/v1/processrequest"

def test_reset_clears_log(mock):
    m, url = mock
    requests.get(f"{url}/health")
    m.reset()
    assert m.request_log() == []

def test_transaction_status(mock):
    m, url = mock
    r = requests.post(f"{url}/mpesa/transactionstatus/v1/query", json={
        "TransactionID": "QKL8TEST123"
    })
    assert r.json()["ResponseCode"] == "0"

def test_chaining(mock):
    m, url = mock
    result = m.set_stk_result(1037).set_b2c_result("success").set_balance("9999.00")
    assert result is m  # fluent API returns self

def test_account_balance(mock):
    m, url = mock
    r = requests.post(f"{url}/mpesa/accountbalance/v1/query", json={})
    assert r.status_code == 200
    assert r.json()["ResponseCode"] == "0"
