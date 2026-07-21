"""iter76 — Regression tests for the 4 client-visible fixes.

Covers:
  1. GET /api/vip/daily-closing works for `normal` clients (was 403 before).
  2. POST /api/vip/convert audit-log fee is ALWAYS 0.01 USDT and the numeric
     balance impact still respects the VIP rate for the primary conversion.
  3. GET /api/me/transactions surfaces `payout_tx_hash`, `crypto_network` and
     the pre-computed `explorer_url` for both withdrawals and order payouts.
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient


BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BACKEND_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BACKEND_URL = line.split("=", 1)[1].strip()
                break
API = f"{BACKEND_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
if not MONGO_URL or not DB_NAME:
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("MONGO_URL="):
                MONGO_URL = line.split("=", 1)[1].strip()
            if line.startswith("DB_NAME="):
                DB_NAME = line.split("=", 1)[1].strip()

NORMAL = {"session_token": "test_session_normal_X"}
VIP = {"session_token": "test_session_vip_X"}
EMPLOYEE = {"session_token": "test_session_employee_X"}
ADMIN = {"session_token": "test_session_admin_X"}


# ============================================================
# Issue #1 — Daily closing PDF
# ============================================================

def test_daily_closing_pdf_normal_client():
    r = requests.get(f"{API}/vip/daily-closing", cookies=NORMAL)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"


def test_daily_closing_pdf_employee_still_forbidden():
    r = requests.get(f"{API}/vip/daily-closing", cookies=EMPLOYEE)
    assert r.status_code == 403


# ============================================================
# Issue #4 — Convert fee always in USDT (iter77 model)
# ============================================================

@pytest.fixture
def vip_balance_ready():
    """Ensure the VIP test user has enough USDT for a round-trip conversion.
    We seed 5 USDT, run the test, then restore whatever was there."""
    cli = MongoClient(MONGO_URL)
    coll = cli[DB_NAME].users
    original = coll.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
    coll.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balances.USDT": 5.0}},
    )
    yield
    if original and "vip_balances" in original:
        coll.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": original["vip_balances"]}},
        )
    cli.close()


def test_convert_fee_is_always_001_usdt_regardless_of_destination(vip_balance_ready):
    """iter77 — Whatever the destination currency, `usdt_fee` in the API
    response is always exactly 0.01 USDT, and the destination now receives
    the FULL equivalent (`amount_from × rate`) with the fee charged
    separately from the client's USDT balance."""
    r = requests.post(
        f"{API}/vip/convert",
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 2},
        cookies=VIP,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usdt_fee"] == 0.01, body
    # iter77 — Destination now receives the FULL equivalent (no fee deduction).
    expected_amount_to = round(2 * body["rate"], 4)
    assert body["amount_to"] == expected_amount_to, (
        f"Expected amount_to={expected_amount_to}, got {body['amount_to']}"
    )


def test_convert_requires_usdt_balance_for_fee(vip_balance_ready):
    """iter77 — When source == USDT, the client's USDT balance must cover
    both the conversion amount AND the 0.01 fee. Trying to convert the FULL
    balance (with no room for the fee) must be rejected."""
    r = requests.post(
        f"{API}/vip/convert",
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 5},  # exactly all
        cookies=VIP,
    )
    assert r.status_code == 400, r.text
    assert "insuficiente" in r.text.lower() or "insufficient" in r.text.lower()


def test_convert_debits_source_and_fee_separately(vip_balance_ready):
    """iter77 — After a USDT → CUP conversion of 2 USDT, the client's USDT
    balance should have dropped by exactly 2.01 (amount + fee), not 2."""
    cli = MongoClient(MONGO_URL)
    coll = cli[DB_NAME].users
    before = coll.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
    before_usdt = float(before.get("vip_balances", {}).get("USDT", 0))
    r = requests.post(
        f"{API}/vip/convert",
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 2},
        cookies=VIP,
    )
    assert r.status_code == 200, r.text
    after = coll.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
    after_usdt = float(after.get("vip_balances", {}).get("USDT", 0))
    debited = round(before_usdt - after_usdt, 6)
    assert debited == 2.01, f"Expected 2.01 USDT debited, got {debited}"
    cli.close()


def test_convert_response_no_longer_exposes_fee_in_to_code(vip_balance_ready):
    """iter77 — `fee_in_to_code` was removed from the response because the
    fee is no longer denominated in the destination currency."""
    r = requests.post(
        f"{API}/vip/convert",
        json={"from_code": "USDT", "to_code": "CUP", "amount_from": 2},
        cookies=VIP,
    )
    assert r.status_code == 200
    body = r.json()
    assert "fee_in_to_code" not in body


# ============================================================
# Issue #3 — TX hash + explorer_url in /me/transactions
# ============================================================

def test_me_transactions_exposes_payout_hash_and_explorer():
    """Backend must surface the crypto-payout evidence directly in the
    /me/transactions response so the client detail modal can render it
    without extra requests. Injects a synthetic completed crypto order
    into the DB, calls the endpoint, verifies fields, then cleans up."""
    cli = MongoClient(MONGO_URL)
    coll = cli[DB_NAME].orders
    order_id = f"iter76_test_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": order_id,
        "user_id": "user_test_normal01",
        "user_name": "Iter76 Test",
        "user_email": "iter76@test.local",
        "from_code": "USD",
        "to_code": "USDT",
        "amount_from": 100.0,
        "amount_to": 99.5,
        "rate_applied": 0.995,
        "commission_percent": 0.0,
        "delivery_method": "crypto",
        "delivery_details": "wallet TRC20 TxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxT",
        "status": "completed",
        "payout_tx_hash": "3e2c1a" + "0" * 58,
        "created_at": "2026-02-17T10:00:00+00:00",
        "updated_at": "2026-02-17T11:00:00+00:00",
    }
    coll.insert_one(doc)
    try:
        r = requests.get(
            f"{API}/me/transactions",
            params={"direction": "out"},
            cookies={"session_token": "test_session_normal_X"},
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        matches = [it for it in items if it.get("ref_id") == order_id]
        assert len(matches) == 1, f"Test order not found in items. Sample: {items[:2]}"
        tx = matches[0]
        assert tx["payout_tx_hash"] == doc["payout_tx_hash"]
        assert tx["crypto_network"] == "TRC20", tx
        assert tx["explorer_url"] == f"https://tronscan.org/#/transaction/{doc['payout_tx_hash']}"
    finally:
        coll.delete_one({"id": order_id})
        cli.close()


def test_me_transactions_withdrawal_exposes_explorer_url_from_stored_network():
    """For withdrawals we store `crypto_network` on the doc directly (no
    inference from delivery_details needed). Verify the explorer URL is
    built for supported networks and empty for unsupported ones."""
    cli = MongoClient(MONGO_URL)
    coll = cli[DB_NAME].withdrawals
    with_id = f"iter76_wd_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": with_id,
        "user_id": "user_test_normal01",
        "user_name": "Iter76 Test",
        "user_email": "iter76@test.local",
        "amount_usd": 50.0,
        "currency": "USDT",
        "method": "crypto",
        "crypto_network": "BEP20",
        "details": "0x1234567890abcdef",
        "beneficiary_name": "Iter76",
        "status": "paid",
        "payout_tx_hash": "0x" + "a" * 62,
        "created_at": "2026-02-17T10:00:00+00:00",
        "updated_at": "2026-02-17T11:00:00+00:00",
    }
    coll.insert_one(doc)
    try:
        r = requests.get(
            f"{API}/me/transactions",
            params={"direction": "out"},
            cookies={"session_token": "test_session_normal_X"},
        )
        assert r.status_code == 200
        matches = [it for it in r.json()["items"] if it.get("ref_id") == with_id]
        assert len(matches) == 1
        assert matches[0]["explorer_url"] == f"https://bscscan.com/tx/{doc['payout_tx_hash']}"
        assert matches[0]["crypto_network"] == "BEP20"
    finally:
        coll.delete_one({"id": with_id})
        cli.close()


def test_me_transactions_no_explorer_url_for_transfer_payouts():
    """Transfer payouts should not surface an explorer URL — that would be
    a broken link. Verify explorer_url is empty/absent for non-crypto refs."""
    cli = MongoClient(MONGO_URL)
    coll = cli[DB_NAME].orders
    order_id = f"iter76_transfer_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": order_id,
        "user_id": "user_test_normal01",
        "user_name": "Iter76 Transfer",
        "user_email": "iter76t@test.local",
        "from_code": "USDT",
        "to_code": "CUP",
        "amount_from": 5.0,
        "amount_to": 1900.0,
        "rate_applied": 380.0,
        "commission_percent": 0.0,
        "delivery_method": "transfer",
        "delivery_details": "banco X · cuenta 1234",
        "status": "completed",
        "payout_tx_hash": "",  # never populated for transfer
        "created_at": "2026-02-17T10:00:00+00:00",
        "updated_at": "2026-02-17T11:00:00+00:00",
    }
    coll.insert_one(doc)
    try:
        r = requests.get(
            f"{API}/me/transactions",
            params={"direction": "out"},
            cookies={"session_token": "test_session_normal_X"},
        )
        assert r.status_code == 200
        matches = [it for it in r.json()["items"] if it.get("ref_id") == order_id]
        assert len(matches) == 1
        tx = matches[0]
        assert tx["explorer_url"] == ""
        assert tx["crypto_network"] == ""
        assert tx["payout_tx_hash"] == ""
    finally:
        coll.delete_one({"id": order_id})
        cli.close()
