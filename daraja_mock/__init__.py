"""
daraja-mock — Local test server for the Safaricom M-Pesa Daraja v3 API.

Provides realistic responses for STK Push, B2C, C2B, and account balance
without requiring a Safaricom developer account or sandbox credentials.

Scenarios control what the mock returns — configure them before your test
to simulate success, user cancellation, insufficient funds, timeout, etc.

Usage in pytest:
    from daraja_mock import DarajaMock

    def test_stk_push():
        mock = DarajaMock()
        with mock.run() as base_url:
            # Point your MpesaClient at base_url
            client = MpesaClient(
                consumer_key="any", consumer_secret="any",
                shortcode="174379", passkey="any",
                base_url=base_url,  # override in your client
            )
            result = client.stk_push("0712345678", 100, "ref")
            assert result.checkout_request_id == mock.last_stk_checkout_id

Run as a standalone server:
    python -m daraja_mock          # starts on http://localhost:8765
    python -m daraja_mock --port 9000
"""
from __future__ import annotations

import json
import random
import string
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse, parse_qs


class Scenario(str, Enum):
    """What the mock returns for the next STK Push or B2C call."""
    SUCCESS              = "success"
    USER_CANCELLED       = "user_cancelled"       # ResultCode 1032
    INSUFFICIENT_FUNDS   = "insufficient_funds"   # ResultCode 1
    TIMED_OUT            = "timed_out"            # ResultCode 1037
    WRONG_PIN            = "wrong_pin"            # ResultCode 2001
    SYSTEM_ERROR         = "system_error"         # ResultCode 17
    AUTH_FAILURE         = "auth_failure"         # HTTP 400 on /oauth


def _rand(prefix: str = "", length: int = 10) -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


@dataclass
class CallRecord:
    """Records a call made to the mock for assertion in tests."""
    endpoint: str
    method: str
    body: dict
    received_at: float = field(default_factory=time.time)


class DarajaMock:
    """Configurable mock server for the Safaricom M-Pesa Daraja v3 API.

    Usage::

        mock = DarajaMock()
        mock.set_scenario(Scenario.USER_CANCELLED)

        with mock.run() as base_url:
            # make API calls to base_url
            ...

        # After the context: inspect calls
        assert len(mock.calls) == 1
        assert mock.calls[0].endpoint == "/mpesa/stkpush/v1/processrequest"
    """

    def __init__(self, port: int = 0):
        self._port = port  # 0 = OS picks a free port
        self._scenario = Scenario.SUCCESS
        self._scenario_queue: list[Scenario] = []
        self.calls: list[CallRecord] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.last_stk_checkout_id: str = ""
        self.last_b2c_conversation_id: str = ""
        self.last_token: str = "mock_token_00000"

    def set_scenario(self, scenario: Scenario) -> None:
        """Set the scenario for ALL subsequent calls."""
        self._scenario = scenario
        self._scenario_queue.clear()

    def queue_scenarios(self, *scenarios: Scenario) -> None:
        """Queue scenarios — each call consumes one. Falls back to SUCCESS."""
        self._scenario_queue.extend(scenarios)

    def reset(self) -> None:
        """Clear calls and reset to SUCCESS scenario."""
        self.calls.clear()
        self._scenario = Scenario.SUCCESS
        self._scenario_queue.clear()

    def _next_scenario(self) -> Scenario:
        if self._scenario_queue:
            return self._scenario_queue.pop(0)
        return self._scenario

    def _make_handler(self) -> type:
        mock = self  # capture for closure

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # suppress default access log

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if not length:
                    return {}
                raw = self.rfile.read(length)
                try:
                    return json.loads(raw)
                except Exception:
                    return {}

            def _respond(self, status: int, body: dict) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(payload))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                path = urlparse(self.path).path
                mock.calls.append(CallRecord(path, "GET", {}))

                if path == "/oauth/v1/generate":
                    scenario = mock._next_scenario()
                    if scenario == Scenario.AUTH_FAILURE:
                        self._respond(400, {
                            "errorCode": "400.008.01",
                            "errorMessage": "Invalid credentials",
                        })
                    else:
                        token = _rand("mock_token_")
                        mock.last_token = token
                        self._respond(200, {
                            "access_token": token,
                            "expires_in": "3599",
                        })
                else:
                    self._respond(404, {"error": "Not found"})

            def do_POST(self):
                path = urlparse(self.path).path
                body = self._read_body()
                scenario = mock._next_scenario()
                mock.calls.append(CallRecord(path, "POST", body))

                # ── STK Push ────────────────────────────────────────────────
                if path == "/mpesa/stkpush/v1/processrequest":
                    checkout_id = _rand("ws_CO_")
                    merchant_id = _rand("29115-")
                    mock.last_stk_checkout_id = checkout_id
                    if scenario == Scenario.SUCCESS:
                        self._respond(200, {
                            "MerchantRequestID": merchant_id,
                            "CheckoutRequestID": checkout_id,
                            "ResponseCode": "0",
                            "ResponseDescription": "Success. Request accepted for processing",
                            "CustomerMessage": "Success. Request accepted for processing",
                        })
                    elif scenario in (Scenario.SYSTEM_ERROR,):
                        self._respond(500, {
                            "errorCode": "500.001.1001",
                            "errorMessage": "Internal server error",
                        })
                    else:
                        # Initiation succeeds; failure comes via callback
                        self._respond(200, {
                            "MerchantRequestID": merchant_id,
                            "CheckoutRequestID": checkout_id,
                            "ResponseCode": "0",
                            "ResponseDescription": "Success. Request accepted for processing",
                            "CustomerMessage": "Success. Request accepted for processing",
                        })

                # ── STK Query ──────────────────────────────────────────────
                elif path == "/mpesa/stkpushquery/v1/query":
                    codes = {
                        Scenario.SUCCESS:            ("0",    "The service request is processed successfully."),
                        Scenario.USER_CANCELLED:     ("1032", "Request cancelled by user"),
                        Scenario.INSUFFICIENT_FUNDS: ("1",    "The balance is insufficient for the transaction"),
                        Scenario.TIMED_OUT:          ("1037", "DS timeout user cannot be reached"),
                        Scenario.WRONG_PIN:          ("2001", "The initiator information is invalid"),
                        Scenario.SYSTEM_ERROR:       ("17",   "System error"),
                    }
                    code, desc = codes.get(scenario, ("0", "Success"))
                    self._respond(200, {
                        "ResponseCode":       "0",
                        "ResponseDescription": "The service request has been accepted successfully",
                        "MerchantRequestID":  _rand("29115-"),
                        "CheckoutRequestID":  body.get("CheckoutRequestID", _rand("ws_CO_")),
                        "ResultCode":         code,
                        "ResultDesc":         desc,
                    })

                # ── B2C ────────────────────────────────────────────────────
                elif path == "/mpesa/b2c/v3/paymentrequest":
                    conv_id = _rand("AG_")
                    mock.last_b2c_conversation_id = conv_id
                    if scenario == Scenario.SUCCESS:
                        self._respond(200, {
                            "ConversationID":           conv_id,
                            "OriginatorConversationID": body.get("OriginatorConversationID", _rand()),
                            "ResponseCode":             "0",
                            "ResponseDescription":      "Accept the service request successfully.",
                        })
                    elif scenario == Scenario.INSUFFICIENT_FUNDS:
                        self._respond(200, {
                            "ResponseCode":        "1",
                            "ResponseDescription": "Insufficient funds in your account",
                        })
                    else:
                        self._respond(400, {
                            "errorCode":    "400.002.02",
                            "errorMessage": "Bad request",
                        })

                # ── C2B URL registration ────────────────────────────────────
                elif path == "/mpesa/c2b/v1/registerurl":
                    self._respond(200, {
                        "ConversationID": "",
                        "OriginatorCoversationID": "",
                        "ResponseDescription": "success",
                    })

                # ── Account balance ─────────────────────────────────────────
                elif path == "/mpesa/accountbalance/v1/query":
                    self._respond(200, {
                        "ConversationID":           _rand("AG_"),
                        "OriginatorConversationID": _rand(),
                        "ResponseCode":             "0",
                        "ResponseDescription":      "Accept the service request successfully.",
                    })

                else:
                    self._respond(404, {"error": f"Endpoint {path!r} not implemented in mock"})

        return Handler

    @contextmanager
    def run(self):
        """Context manager: start the mock server, yield base_url, then stop.

        Example::
            with mock.run() as base_url:
                client = MyClient(base_url=base_url)
                ...
        """
        handler = self._make_handler()
        self._server = HTTPServer(("127.0.0.1", self._port), handler)
        port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            self._server.shutdown()
            self._thread.join(timeout=2)
            self._server = None
            self._thread = None

    def build_stk_callback(
        self,
        checkout_request_id: str | None = None,
        scenario: Scenario = Scenario.SUCCESS,
    ) -> dict:
        """Build a realistic STK Push callback payload.

        Use this to simulate the webhook Safaricom POSTs to your callback URL.

        Example::
            payload = mock.build_stk_callback(scenario=Scenario.USER_CANCELLED)
            response = client.post("/mpesa/callback", json=payload)
        """
        checkout_id = checkout_request_id or mock.last_stk_checkout_id or _rand("ws_CO_")
        merchant_id = _rand("29115-")

        if scenario == Scenario.SUCCESS:
            return {
                "Body": {
                    "stkCallback": {
                        "MerchantRequestID":  merchant_id,
                        "CheckoutRequestID":  checkout_id,
                        "ResultCode":         0,
                        "ResultDesc":         "The service request is processed successfully.",
                        "CallbackMetadata": {
                            "Item": [
                                {"Name": "Amount",              "Value": 100},
                                {"Name": "MpesaReceiptNumber",  "Value": _rand("NLJ")},
                                {"Name": "TransactionDate",     "Value": int(datetime.now().strftime("%Y%m%d%H%M%S"))},
                                {"Name": "PhoneNumber",         "Value": 254712345678},
                            ]
                        },
                    }
                }
            }
        else:
            codes = {
                Scenario.USER_CANCELLED:     (1032, "Request cancelled by user"),
                Scenario.INSUFFICIENT_FUNDS: (1,    "The balance is insufficient"),
                Scenario.TIMED_OUT:          (1037, "DS timeout user cannot be reached"),
                Scenario.WRONG_PIN:          (2001, "The initiator information is invalid"),
                Scenario.SYSTEM_ERROR:       (17,   "System error"),
            }
            code, desc = codes.get(scenario, (1032, "Unknown failure"))
            return {
                "Body": {
                    "stkCallback": {
                        "MerchantRequestID": merchant_id,
                        "CheckoutRequestID": checkout_id,
                        "ResultCode":        code,
                        "ResultDesc":        desc,
                    }
                }
            }


# ── Module-level convenience instance ─────────────────────────────────────────

mock = DarajaMock()
