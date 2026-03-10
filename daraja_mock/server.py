"""
daraja_mock — local test server for Safaricom M-Pesa Daraja v3 API.

Provides configurable Flask endpoints matching Daraja sandbox:
  /oauth/v1/generate         — OAuth token
  /mpesa/stkpush/v1/processrequest  — STK Push
  /mpesa/stkpushquery/v1/query      — STK Query
  /mpesa/b2c/v3/paymentrequest      — B2C
  /mpesa/transactionstatus/v1/query — Transaction Status
  /mpesa/accountbalance/v1/query    — Account Balance

Usage:
    from daraja_mock import DarajaMock
    mock = DarajaMock()
    mock.run(port=8080)           # blocking

    # Or use as pytest fixture via run_thread()
    url = mock.run_thread(port=8080)

    # Configure scenarios
    mock.set_stk_result(0)        # success
    mock.set_stk_result(1032)     # user cancelled
    mock.set_b2c_result("success")
"""

import hashlib
import json
import random
import string
import threading
import time
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify, request


def _random_id(prefix: str = "", length: int = 10) -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


class DarajaMock:
    """
    In-process mock for Safaricom Daraja v3 API.

    All responses match the Daraja sandbox format exactly.
    Configure result codes before each test to simulate scenarios.
    """

    def __init__(self, consumer_key: str = "test_key", consumer_secret: str = "test_secret"):
        self.consumer_key    = consumer_key
        self.consumer_secret = consumer_secret
        self.app             = Flask(__name__)
        self._stk_result_code     = 0        # 0=success, 1032=cancelled, 1037=timeout
        self._b2c_result          = "success"
        self._balance_amount      = "10000.00"
        self._token_expire        = 3600
        self._request_log: list   = []
        self._configure_routes()

    # ── Configuration ─────────────────────────────────────────────────────────

    def set_stk_result(self, result_code: int) -> "DarajaMock":
        """Set the ResultCode returned by STK Push query."""
        self._stk_result_code = result_code
        return self

    def set_b2c_result(self, result: str) -> "DarajaMock":
        """'success' | 'insufficient_funds' | 'invalid_msisdn'"""
        self._b2c_result = result
        return self

    def set_balance(self, amount: str) -> "DarajaMock":
        """Set account balance string e.g. '5000.00'"""
        self._balance_amount = amount
        return self

    def request_log(self) -> list:
        """Return all recorded requests (method, path, body)."""
        return list(self._request_log)

    def reset(self) -> "DarajaMock":
        """Reset all scenarios to defaults and clear request log."""
        self._stk_result_code = 0
        self._b2c_result      = "success"
        self._balance_amount  = "10000.00"
        self._request_log.clear()
        return self

    # ── Flask routes ───────────────────────────────────────────────────────────

    def _configure_routes(self) -> None:
        app = self.app

        @app.before_request
        def _log():
            body = request.get_json(silent=True) or {}
            self._request_log.append({
                "method": request.method,
                "path":   request.path,
                "body":   body,
                "ts":     _timestamp(),
            })

        @app.route("/oauth/v1/generate")
        def oauth_token():
            return jsonify({
                "access_token": f"mock_token_{_random_id(length=20)}",
                "expires_in":   str(self._token_expire),
            })

        @app.route("/mpesa/stkpush/v1/processrequest", methods=["POST"])
        def stk_push():
            checkout_id  = _random_id("ws_CO_", 15)
            merchant_id  = _random_id("29115", 10)
            return jsonify({
                "MerchantRequestID":  merchant_id,
                "CheckoutRequestID":  checkout_id,
                "ResponseCode":       "0",
                "ResponseDescription": "Success. Request accepted for processing",
                "CustomerMessage":    "Success. Request accepted for processing",
            })

        @app.route("/mpesa/stkpushquery/v1/query", methods=["POST"])
        def stk_query():
            code = self._stk_result_code
            desc_map = {
                0:    "The service request is processed successfully.",
                1:    "The balance is insufficient for the transaction.",
                1001: "The initiator information is invalid.",
                1032: "Request cancelled by user.",
                1037: "DS timeout user cannot be reached.",
                2001: "The initiator information is invalid.",
            }
            return jsonify({
                "ResponseCode":        "0",
                "ResponseDescription": "The service request has been accepted successfully",
                "MerchantRequestID":   _random_id("29115", 10),
                "CheckoutRequestID":   _random_id("ws_CO_", 15),
                "ResultCode":          str(code),
                "ResultDesc":          desc_map.get(code, f"Error {code}"),
            })

        @app.route("/mpesa/b2c/v3/paymentrequest", methods=["POST"])
        def b2c():
            result_map = {
                "success":            ("0",  "The service request is processed successfully."),
                "insufficient_funds": ("1",  "Initiator account insufficient funds"),
                "invalid_msisdn":     ("17", "System internal error."),
            }
            code, desc = result_map.get(self._b2c_result, ("0", "Success"))
            return jsonify({
                "ConversationID":         _random_id("AG_", 15),
                "OriginatorConversationID": _random_id("16740", 10),
                "ResponseCode":           "0",
                "ResponseDescription":    "Accept the service request successfully.",
            })

        @app.route("/mpesa/transactionstatus/v1/query", methods=["POST"])
        def transaction_status():
            return jsonify({
                "ConversationID":         _random_id("AG_", 15),
                "OriginatorConversationID": _random_id("16740", 10),
                "ResponseCode":           "0",
                "ResponseDescription":    "Accept the service request successfully.",
            })

        @app.route("/mpesa/accountbalance/v1/query", methods=["POST"])
        def account_balance():
            return jsonify({
                "ConversationID":         _random_id("AG_", 15),
                "OriginatorConversationID": _random_id("16740", 10),
                "ResponseCode":           "0",
                "ResponseDescription":    "Accept the service request successfully.",
            })

        @app.route("/mock/balance-callback", methods=["POST"])
        def balance_callback():
            """Receive async balance result (use in tests as callback URL)."""
            return jsonify({"result": "received"})

        @app.route("/health")
        def health():
            return jsonify({"status": "ok", "version": "1.0.0"})

    # ── Server control ─────────────────────────────────────────────────────────

    def run(self, host: str = "127.0.0.1", port: int = 18080) -> None:
        """Start blocking server (use run_thread for tests)."""
        self.app.run(host=host, port=port, debug=False)

    def run_thread(self, host: str = "127.0.0.1", port: int = 18080) -> str:
        """
        Start non-blocking server in a daemon thread.
        Returns base URL e.g. 'http://127.0.0.1:18080'.
        """
        t = threading.Thread(
            target=lambda: self.app.run(host=host, port=port, debug=False, use_reloader=False),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)  # brief settle
        return f"http://{host}:{port}"
