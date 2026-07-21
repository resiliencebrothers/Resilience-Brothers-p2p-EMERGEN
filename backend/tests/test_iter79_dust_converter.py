"""iter79 — Dust converter endpoints.

Verifies:
1. GET /api/vip/dust returns the empty list when the user has no dust.
2. GET /api/vip/dust surfaces only balances with USDT eq < 5.0.
3. POST /api/vip/convert-dust sweeps ALL dust into USDT, charges a
   FLAT 0.01 USDT fee once, and returns the swept items.
4. After sweep, dust balances are zeroed and USDT balance grew by
   the sum of dust equivalents minus the flat fee.
5. Sweep audit_log rows show up in /api/me/transactions?direction=conversion
   as one row per swept currency, each `conversion_subtype: "small_balance"`
   and only the FIRST row carries the 0.01 USDT fee.
6. Employees are forbidden.
"""
import os
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, VIP_TOKEN, EMPLOYEE_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
VIP_UID = "user_test_vip01"


def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _reset_balances(**bals):
    _db().users.update_one(
        {"user_id": VIP_UID},
        {"$set": {"vip_balances": {k: float(v) for k, v in bals.items()}}},
    )


@pytest.fixture
def clean_ledger():
    """Snapshot balances and wipe any leftover convert audit rows for the
    user so counts are deterministic."""
    db = _db()
    original = db.users.find_one({"user_id": VIP_UID}, {"_id": 0, "vip_balances": 1})
    db.audit_log.delete_many({
        "actor_id": VIP_UID,
        "action": {"$in": ["vip.convert", "vip.convert.dust"]},
    })
    yield
    db.users.update_one(
        {"user_id": VIP_UID},
        {"$set": {"vip_balances": (original or {}).get("vip_balances", {})}},
    )
    db.audit_log.delete_many({
        "actor_id": VIP_UID,
        "action": {"$in": ["vip.convert", "vip.convert.dust"]},
    })


def _h(token=VIP_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _get_balances():
    d = _db().users.find_one({"user_id": VIP_UID}, {"_id": 0, "vip_balances": 1}) or {}
    return d.get("vip_balances", {}) or {}


def test_dust_preview_empty_when_no_dust(clean_ledger):
    _reset_balances(USDT=100.0)
    r = requests.get(f"{BASE_URL}/api/vip/dust", headers=_h(), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["can_convert"] is False
    assert body["reason"] == "no_dust"
    assert body["fee_usdt"] == 0.01
    assert body["threshold_usdt"] == 5.0


def test_dust_preview_lists_only_sub_threshold_non_usdt(clean_ledger):
    # 3 USDT worth of CUP (dust), 10 USDT worth of USD (NOT dust), 100 USDT (excluded).
    _reset_balances(USDT=100.0, CUP=1185.0, USD=10.0)
    r = requests.get(f"{BASE_URL}/api/vip/dust", headers=_h(), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [it["currency"] for it in body["items"]]
    assert "CUP" in codes
    assert "USD" not in codes
    assert "USDT" not in codes
    assert body["can_convert"] is True
    assert body["total_usdt"] > 0


def test_convert_dust_sweeps_and_charges_flat_fee(clean_ledger):
    # Seed multiple small balances.
    _reset_balances(USDT=1.0, CUP=395.0, USDW23=1.0)  # each < 5 USDT
    pre = requests.get(f"{BASE_URL}/api/vip/dust", headers=_h(), timeout=30).json()
    total_pre = pre["total_usdt"]
    n_items = len(pre["items"])
    assert n_items >= 1

    r = requests.post(f"{BASE_URL}/api/vip/convert-dust", headers=_h(), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["fee_usdt"] == 0.01
    assert body["credited_usdt"] == pytest.approx(total_pre, rel=1e-3)
    assert len(body["items"]) == n_items

    # Balances: dust currencies now zero, USDT grew by (total_pre - 0.01).
    bals = _get_balances()
    for it in body["items"]:
        assert bals.get(it["currency"], 0) == pytest.approx(0.0, abs=1e-9)
    # New USDT ≈ 1.0 (starting) + total_pre - 0.01 fee
    assert bals.get("USDT", 0) == pytest.approx(1.0 + total_pre - 0.01, abs=1e-3)


def test_convert_dust_appears_in_history_with_small_balance_subtype(clean_ledger):
    _reset_balances(USDT=1.0, CUP=395.0, USDW23=1.0)
    r = requests.post(f"{BASE_URL}/api/vip/convert-dust", headers=_h(), timeout=30)
    assert r.status_code == 200, r.text
    n_swept = len(r.json()["items"])

    r_hist = requests.get(
        f"{BASE_URL}/api/me/transactions?direction=conversion",
        headers=_h(), timeout=30,
    )
    assert r_hist.status_code == 200, r_hist.text
    items = r_hist.json()["items"]
    assert len(items) == n_swept
    for it in items:
        assert it["direction"] == "conversion"
        assert it["conversion_subtype"] == "small_balance"
        assert it["is_dust_batch"] is True
        assert it["method"] == "dust_sweep"
        assert it["to_code"] == "USDT"
    # Only ONE row carries the 0.01 fee.
    fee_rows = [it for it in items if it["usdt_fee"] > 0]
    assert len(fee_rows) == 1
    assert fee_rows[0]["usdt_fee"] == pytest.approx(0.01, rel=1e-6)


def test_convert_dust_refuses_without_usdt_for_fee(clean_ledger):
    _reset_balances(USDT=0.0, CUP=395.0)  # dust exists but no fee
    r = requests.post(f"{BASE_URL}/api/vip/convert-dust", headers=_h(), timeout=30)
    assert r.status_code == 400
    assert "0.01 USDT" in r.json()["detail"]


def test_convert_dust_refuses_when_no_dust(clean_ledger):
    _reset_balances(USDT=100.0)  # no dust at all
    r = requests.post(f"{BASE_URL}/api/vip/convert-dust", headers=_h(), timeout=30)
    assert r.status_code == 400
    assert "No tienes saldos pequeños" in r.json()["detail"]


def test_convert_dust_employee_forbidden(clean_ledger):
    r = requests.post(f"{BASE_URL}/api/vip/convert-dust",
                      headers=_h(EMPLOYEE_TOKEN), timeout=30)
    assert r.status_code == 403
