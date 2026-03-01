"""daraja-mock test suite — no Safaricom account needed."""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime

import pytest
from daraja_mock import DarajaMock, Scenario


def get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def post(url: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def mock():
    m = DarajaMock()
    yield m


class TestOAuth:
    def test_token_returned(self, mock):
        with mock.run() as base:
            status, body = get(f"{base}/oauth/v1/generate")
        assert status == 200
        assert "access_token" in body
        assert body["expires_in"] == "3599"

    def test_token_is_string(self, mock):
        with mock.run() as base:
            _, body = get(f"{base}/oauth/v1/generate")
        assert isinstance(body["access_token"], str)
        assert len(body["access_token"]) > 5

    def test_auth_failure_scenario(self, mock):
        mock.set_scenario(Scenario.AUTH_FAILURE)
        with mock.run() as base:
            status, body = get(f"{base}/oauth/v1/generate")
        assert status == 400
        assert "errorCode" in body

    def test_call_is_recorded(self, mock):
        with mock.run() as base:
            get(f"{base}/oauth/v1/generate")
        assert len(mock.calls) == 1
        assert mock.calls[0].endpoint == "/oauth/v1/generate"


class TestSTKPush:
    def test_success_response(self, mock):
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/stkpush/v1/processrequest", {
                "BusinessShortCode": "174379",
                "Amount": 100,
                "PartyA": "254712345678",
                "PhoneNumber": "254712345678",
                "CallBackURL": "https://example.com/callback",
                "AccountReference": "Test001",
                "TransactionDesc": "Test payment",
            })
        assert status == 200
        assert body["ResponseCode"] == "0"
        assert "CheckoutRequestID" in body
        assert "MerchantRequestID" in body

    def test_checkout_id_stored(self, mock):
        with mock.run() as base:
            _, body = post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 100})
        assert mock.last_stk_checkout_id == body["CheckoutRequestID"]

    def test_system_error_scenario(self, mock):
        mock.set_scenario(Scenario.SYSTEM_ERROR)
        with mock.run() as base:
            status, _ = post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 100})
        assert status == 500

    def test_call_body_recorded(self, mock):
        with mock.run() as base:
            post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 250, "PhoneNumber": "254712345678"})
        assert mock.calls[0].body["Amount"] == 250
        assert mock.calls[0].body["PhoneNumber"] == "254712345678"


class TestSTKQuery:
    def test_success_query(self, mock):
        with mock.run() as base:
            _, push = post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 100})
            _, query = post(f"{base}/mpesa/stkpushquery/v1/query", {
                "CheckoutRequestID": push["CheckoutRequestID"]
            })
        assert query["ResultCode"] == "0"

    def test_user_cancelled_scenario(self, mock):
        mock.queue_scenarios(Scenario.SUCCESS, Scenario.USER_CANCELLED)
        with mock.run() as base:
            _, push = post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 100})
            _, query = post(f"{base}/mpesa/stkpushquery/v1/query", {
                "CheckoutRequestID": push["CheckoutRequestID"]
            })
        assert query["ResultCode"] == "1032"
        assert "cancel" in query["ResultDesc"].lower()

    def test_insufficient_funds_scenario(self, mock):
        mock.queue_scenarios(Scenario.SUCCESS, Scenario.INSUFFICIENT_FUNDS)
        with mock.run() as base:
            post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 9999})
            _, query = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
        assert query["ResultCode"] == "1"

    def test_timed_out_scenario(self, mock):
        mock.queue_scenarios(Scenario.SUCCESS, Scenario.TIMED_OUT)
        with mock.run() as base:
            post(f"{base}/mpesa/stkpush/v1/processrequest", {"Amount": 100})
            _, query = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
        assert query["ResultCode"] == "1037"


class TestB2C:
    def test_success_response(self, mock):
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/b2c/v3/paymentrequest", {
                "InitiatorName": "testapi",
                "Amount": 500,
                "PartyA": "600000",
                "PartyB": "254712345678",
                "Remarks": "Disbursement",
                "QueueTimeOutURL": "https://example.com/timeout",
                "ResultURL": "https://example.com/result",
            })
        assert status == 200
        assert body["ResponseCode"] == "0"
        assert "ConversationID" in body

    def test_conversation_id_stored(self, mock):
        with mock.run() as base:
            _, body = post(f"{base}/mpesa/b2c/v3/paymentrequest", {"Amount": 500})
        assert mock.last_b2c_conversation_id == body["ConversationID"]

    def test_insufficient_funds(self, mock):
        mock.set_scenario(Scenario.INSUFFICIENT_FUNDS)
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/b2c/v3/paymentrequest", {"Amount": 999999})
        assert body["ResponseCode"] == "1"


class TestC2BRegistration:
    def test_url_registration(self, mock):
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/c2b/v1/registerurl", {
                "ShortCode": "600000",
                "ResponseType": "Completed",
                "ConfirmationURL": "https://example.com/confirm",
                "ValidationURL": "https://example.com/validate",
            })
        assert status == 200
        assert "success" in body.get("ResponseDescription", "").lower()


class TestAccountBalance:
    def test_success(self, mock):
        with mock.run() as base:
            status, body = post(f"{base}/mpesa/accountbalance/v1/query", {
                "InitiatorName": "testapi",
                "PartyA": "600000",
                "IdentifierType": "4",
                "QueueTimeOutURL": "https://example.com/timeout",
                "ResultURL": "https://example.com/result",
            })
        assert status == 200
        assert body["ResponseCode"] == "0"


class TestCallbackBuilders:
    def test_success_callback_structure(self, mock):
        cb = mock.build_stk_callback(scenario=Scenario.SUCCESS)
        stk = cb["Body"]["stkCallback"]
        assert stk["ResultCode"] == 0
        items = {i["Name"]: i["Value"] for i in stk["CallbackMetadata"]["Item"]}
        assert "Amount" in items
        assert "MpesaReceiptNumber" in items
        assert "PhoneNumber" in items

    def test_failure_callback_no_metadata(self, mock):
        cb = mock.build_stk_callback(scenario=Scenario.USER_CANCELLED)
        stk = cb["Body"]["stkCallback"]
        assert stk["ResultCode"] == 1032
        assert "CallbackMetadata" not in stk

    def test_checkout_id_propagated(self, mock):
        cb = mock.build_stk_callback("ws_CO_TEST123", scenario=Scenario.SUCCESS)
        assert cb["Body"]["stkCallback"]["CheckoutRequestID"] == "ws_CO_TEST123"

    def test_all_failure_scenarios_have_result_desc(self, mock):
        failure_scenarios = [
            Scenario.USER_CANCELLED, Scenario.INSUFFICIENT_FUNDS,
            Scenario.TIMED_OUT, Scenario.WRONG_PIN, Scenario.SYSTEM_ERROR,
        ]
        for scenario in failure_scenarios:
            cb = mock.build_stk_callback(scenario=scenario)
            stk = cb["Body"]["stkCallback"]
            assert stk["ResultDesc"], f"Missing ResultDesc for {scenario}"


class TestQueueScenarios:
    def test_queue_consumed_in_order(self, mock):
        mock.queue_scenarios(Scenario.SUCCESS, Scenario.USER_CANCELLED, Scenario.TIMED_OUT)
        results = []
        with mock.run() as base:
            for _ in range(3):
                _, body = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
                results.append(body["ResultCode"])
        assert results == ["0", "1032", "1037"]

    def test_queue_falls_back_to_default(self, mock):
        mock.set_scenario(Scenario.USER_CANCELLED)
        mock.queue_scenarios(Scenario.SUCCESS)
        with mock.run() as base:
            _, b1 = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
            _, b2 = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
        assert b1["ResultCode"] == "0"     # queue consumed
        assert b2["ResultCode"] == "1032"  # fallback to set_scenario


class TestReset:
    def test_reset_clears_calls(self, mock):
        with mock.run() as base:
            get(f"{base}/oauth/v1/generate")
        assert len(mock.calls) == 1
        mock.reset()
        assert len(mock.calls) == 0

    def test_reset_restores_success_scenario(self, mock):
        mock.set_scenario(Scenario.USER_CANCELLED)
        mock.reset()
        with mock.run() as base:
            _, body = post(f"{base}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
        assert body["ResultCode"] == "0"


class TestConcurrentServers:
    def test_two_mocks_run_independently(self):
        mock_a = DarajaMock()
        mock_b = DarajaMock()
        mock_b.set_scenario(Scenario.USER_CANCELLED)
        with mock_a.run() as url_a, mock_b.run() as url_b:
            _, a = post(f"{url_a}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
            _, b = post(f"{url_b}/mpesa/stkpushquery/v1/query", {"CheckoutRequestID": "x"})
        assert a["ResultCode"] == "0"
        assert b["ResultCode"] == "1032"

    def test_ports_are_different(self):
        mock_a = DarajaMock()
        mock_b = DarajaMock()
        with mock_a.run() as url_a, mock_b.run() as url_b:
            assert url_a != url_b
