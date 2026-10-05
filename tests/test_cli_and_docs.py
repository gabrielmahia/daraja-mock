"""Tests for the command-line entry point, the documentation, and the honest no-op setters.

These exist because the published 1.0.0 shipped a `python -m daraja_mock` that crashed on start (it called DarajaMock(port=...)), a console script that pointed
at a `main` that did not exist, and a README documenting a Scenario class, a context-manager run(), and endpoints that do not exist, while the old tests only
exercised the real API through run_thread()."""
import ast
import importlib
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

import daraja_mock
from daraja_mock import DarajaMock

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
BLOCKS = re.findall(r"```python\n(.*?)```", README, re.S)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── the command ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_python_m_daraja_mock_starts_and_serves_health():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "daraja_mock", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                r = requests.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
                break
            except requests.ConnectionError:
                assert proc.poll() is None, "the server process exited instead of starting"
                time.sleep(0.25)
        else:
            pytest.fail("the server did not start")
        assert r.json()["status"] == "ok"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_console_script_target_exists_and_importing_it_does_not_start_a_server():
    target = re.search(r'^daraja-mock\s*=\s*"([\w.]+):(\w+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert target, "no daraja-mock console script in pyproject.toml"
    assert callable(getattr(importlib.import_module(target.group(1)), target.group(2)))


# ── the documentation cannot drift from the code ───────────────────────────────────────────────────────────────────────
def test_readme_imports_only_names_that_exist():
    for block in BLOCKS:
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.ImportFrom) and node.module == "daraja_mock":
                for alias in node.names:
                    assert hasattr(daraja_mock, alias.name), f"README imports {alias.name}, which does not exist"


def test_readme_calls_only_methods_that_exist():
    for block in BLOCKS:
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "mock":
                assert hasattr(DarajaMock, node.attr), f"README calls mock.{node.attr}, which does not exist"


def test_readme_names_only_endpoints_that_exist():
    documented = set(re.findall(r"`(/(?:oauth|mpesa|mock|health)[^`\s]*)`", README))
    served = {r.rule for r in DarajaMock().app.url_map.iter_rules()}
    assert documented and documented <= served, f"documented but not served: {documented - served}"


def test_the_readme_quickstart_actually_runs():
    exec(compile(BLOCKS[0], "README.md", "exec"), {})  # noqa: S102


# ── behaviour, via Flask's test client (no ports) ──────────────────────────────────────────────────────────────────────
def test_set_stk_result_changes_the_query_result():
    m = DarajaMock()
    client = m.app.test_client()
    assert client.post("/mpesa/stkpushquery/v1/query", json={}).get_json()["ResultCode"] == "0"
    m.set_stk_result(1032)
    assert client.post("/mpesa/stkpushquery/v1/query", json={}).get_json()["ResultCode"] == "1032"


def test_b2c_and_balance_setters_warn_and_change_nothing():
    m = DarajaMock()
    client = m.app.test_client()
    before = client.post("/mpesa/b2c/v3/paymentrequest", json={}).get_json()["ResponseCode"]
    with pytest.warns(UserWarning, match="no effect"):
        m.set_b2c_result("insufficient_funds")
    with pytest.warns(UserWarning, match="no effect"):
        m.set_balance("5.00")
    assert client.post("/mpesa/b2c/v3/paymentrequest", json={}).get_json()["ResponseCode"] == before == "0"


def test_request_log_records_method_path_and_body():
    m = DarajaMock()
    m.app.test_client().post("/mpesa/stkpush/v1/processrequest", json={"Amount": 5})
    entry = m.request_log()[-1]
    assert entry["method"] == "POST" and entry["path"] == "/mpesa/stkpush/v1/processrequest" and entry["body"]["Amount"] == 5
    assert m.reset().request_log() == []
