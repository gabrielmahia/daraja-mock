"""daraja-mock test suite — no network calls, no Safaricom account."""
from __future__ import annotations

import json
import urllib.request
import pytest
from daraja_mock import DarajaMock, Scenario


BASE = "http://127.0.0.1"

def get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())

def post(url: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ── Auth ───────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_token_returned_on_success(self):
        mock = DarajaMock()
        with mock.run() as base:
            status, body = get(f"{base}/oauth/v1/generate")
        assert status == 200
        assert "access_token" in body
        assert body["expires_in"] == "3599"

    def test_token_recorded_on_mock(self):
        mock = DarajaMock()
        with mock.run() as base:
            _, body = get(f"{base}/oauth/v1/generate")
        assert mock.last_token == body["access_token"]

    def test_auth_failure_scenario(self):
        mock = DarajaMock()
        mock.set_scenario(Scenario.AUTH_FAILURE)
        with mock.run() as base:
            status, body = get(f"{base}/oauth/v1/generate")
        assert status == 400
        assert "errorCode" in body

    def test_call_recorded(self):
        mock = DarajaMock()
        with mock.run() as base:
            get(f"{base}/oauth/v1/generate")
        assert len(mock.calls) == 1
        assert mock.calls[0].endpoint == "/oauth/v1/generate"


# ── STK Push ───────────────────────────────────────────────────────────────────

class TestStkPush:
    STK_BODY = {
        "BusinessShortCode": "174379",
        "Password": "dGVzdA==",
        "Timestamp": "20240101120000",
        "TransactionType": "CustomerPayBillOnline",
        "Amount": 100,
        "PartyA": "254712345678",
        "PartyB": "174379",
        "PhoneNumber": "254712345678",
        "CallBackURL": "https://example.com/callback",
        "AccountReference": "TestRef",
        "TransactionDesc": "Test",
    }

    def test_success_returns_checkout_id(self):
        mock = DarajaMock()
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/stkpush/v1/processrequest", self.STK_BODY)
        assert status == 200
        assert body["ResponseCode"] == "0"
        assert "CheckoutRequestID" in body
        assert "MerchantRequestID" in body

    def test_checkout_id_stored_on_mock(self):
        mock = DarajaMock()
        with mock.run() as base:
            _, body = post(f"{base}/mpesa/stkpush/v1/processrequest", self.STK_BODY)
        assert mock.last_stk_checkout_id == body["CheckoutRequestID"]

    def test_system_error_scenario(self):
        mock = DarajaMock()
        mock.set_scenario(Scenario.SYSTEM_ERROR)
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/stkpush/v1/processrequest", self.STK_BODY)
        assert status == 500

    def test_body_recorded_on_call(self):
        mock = DarajaMock()
        with mock.run() as base:
            post(f"{base}/mpesa/stkpush/v1/processrequest", self.STK_BODY)
        assert mock.calls[0].body["Amount"] == 100


# ── STK Query ──────────────────────────────────────────────────────────────────

class TestStkQuery:
    def test_success_result_code_zero(self):
        mock = DarajaMock()
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/stkpushquery/v1/query",
                                 {"CheckoutRequestID": "ws_CO_test"})
        assert status == 200
        assert body["ResultCode"] == "0"

    @pytest.mark.parametrize("scenario,expected_code", [
        (Scenario.USER_CANCELLED,     "1032"),
        (Scenario.INSUFFICIENT_FUNDS, "1"),
        (Scenario.TIMED_OUT,          "1037"),
        (Scenario.WRONG_PIN,          "2001"),
    ])
    def test_failure_scenarios_return_correct_result_codes(self, scenario, expected_code):
        mock = DarajaMock()
        mock.set_scenario(scenario)
        with mock.run() as base:
            _, body = post(f"{base}/mpesa/stkpushquery/v1/query",
                           {"CheckoutRequestID": "ws_CO_test"})
        assert body["ResultCode"] == expected_code


# ── B2C ────────────────────────────────────────────────────────────────────────

class TestB2C:
    B2C_BODY = {
        "InitiatorName": "testapi",
        "SecurityCredential": "dGVzdA==",
        "CommandID": "BusinessPayment",
        "Amount": 500,
        "PartyA": "174379",
        "PartyB": "254712345678",
        "Remarks": "Chama payout",
        "QueueTimeOutURL": "https://example.com/timeout",
        "ResultURL": "https://example.com/result",
        "OriginatorConversationID": "test-conv-001",
    }

    def test_success_returns_conversation_id(self):
        mock = DarajaMock()
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/b2c/v3/paymentrequest", self.B2C_BODY)
        assert status == 200
        assert body["ResponseCode"] == "0"
        assert "ConversationID" in body

    def test_conversation_id_stored_on_mock(self):
        mock = DarajaMock()
        with mock.run() as base:
            _, body = post(f"{base}/mpesa/b2c/v3/paymentrequest", self.B2C_BODY)
        assert mock.last_b2c_conversation_id == body["ConversationID"]

    def test_insufficient_funds_scenario(self):
        mock = DarajaMock()
        mock.set_scenario(Scenario.INSUFFICIENT_FUNDS)
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/b2c/v3/paymentrequest", self.B2C_BODY)
        assert status == 200
        assert body["ResponseCode"] == "1"


# ── Callback builders ──────────────────────────────────────────────────────────

class TestCallbackBuilders:
    def test_success_callback_has_receipt(self):
        mock = DarajaMock()
        cb = mock.build_stk_callback(checkout_request_id="ws_CO_test")
        items = cb["Body"]["stkCallback"]["CallbackMetadata"]["Item"]
        names = [i["Name"] for i in items]
        assert "MpesaReceiptNumber" in names
        assert "Amount" in names
        assert "PhoneNumber" in names

    def test_success_callback_result_code_zero(self):
        mock = DarajaMock()
        cb = mock.build_stk_callback()
        assert cb["Body"]["stkCallback"]["ResultCode"] == 0

    @pytest.mark.parametrize("scenario,expected_code", [
        (Scenario.USER_CANCELLED,     1032),
        (Scenario.INSUFFICIENT_FUNDS, 1),
        (Scenario.TIMED_OUT,          1037),
        (Scenario.WRONG_PIN,          2001),
    ])
    def test_failure_callbacks_have_correct_result_codes(self, scenario, expected_code):
        mock = DarajaMock()
        cb = mock.build_stk_callback(scenario=scenario)
        assert cb["Body"]["stkCallback"]["ResultCode"] == expected_code

    def test_failure_callback_has_no_metadata(self):
        mock = DarajaMock()
        cb = mock.build_stk_callback(scenario=Scenario.USER_CANCELLED)
        assert "CallbackMetadata" not in cb["Body"]["stkCallback"]


# ── Scenario queue ─────────────────────────────────────────────────────────────

class TestScenarioQueue:
    def test_queue_consumed_in_order(self):
        mock = DarajaMock()
        mock.queue_scenarios(Scenario.SUCCESS, Scenario.USER_CANCELLED)
        # Each POST to any endpoint consumes one
        with mock.run() as base:
            _, b1 = post(f"{base}/mpesa/stkpushquery/v1/query",
                         {"CheckoutRequestID": "id1"})
            _, b2 = post(f"{base}/mpesa/stkpushquery/v1/query",
                         {"CheckoutRequestID": "id2"})
        assert b1["ResultCode"] == "0"
        assert b2["ResultCode"] == "1032"

    def test_falls_back_to_success_after_queue_exhausted(self):
        mock = DarajaMock()
        mock.queue_scenarios(Scenario.USER_CANCELLED)
        with mock.run() as base:
            post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "id1"})
            _, b2 = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "id2"})
        assert b2["ResultCode"] == "0"

    def test_reset_clears_calls_and_queue(self):
        mock = DarajaMock()
        mock.queue_scenarios(Scenario.USER_CANCELLED)
        with mock.run() as base:
            post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "id1"})
        mock.reset()
        assert mock.calls == []
        assert mock._scenario_queue == []


# ── Unknown endpoint ───────────────────────────────────────────────────────────

class TestUnknownEndpoint:
    def test_unknown_endpoint_returns_404(self):
        mock = DarajaMock()
        with mock.run() as base:
            status, _ = post(f"{base}/mpesa/unknown/endpoint", {})
        assert status == 404


# ── Multiple runs ──────────────────────────────────────────────────────────────

class TestMultipleRuns:
    def test_mock_can_be_run_multiple_times(self):
        mock = DarajaMock()
        for _ in range(3):
            with mock.run() as base:
                status, _ = get(f"{base}/oauth/v1/generate")
            assert status == 200
            mock.reset()
