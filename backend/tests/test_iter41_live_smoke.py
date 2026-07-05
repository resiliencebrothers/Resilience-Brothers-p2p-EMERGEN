"""Live smoke tests against the public URL for iter55 features."""
import os
import uuid
from datetime import datetime, timezone
import pyotp
import pytest
import requests
from pymongo import MongoClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
# Deterministic TOTP secret for reproducible tests. Documented in
# /app/memory/test_credentials.md — NOT a production credential. Override via
# TEST_TOTP_SECRET env var in CI environments if needed.
TOTP_SECRET = os.environ.get("TEST_TOTP_SECRET", "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")


def _admin_headers():
    return {"Cookie": "session_token=test_session_admin_X"}


def _totp():
    return pyotp.TOTP(TOTP_SECRET).now()


ADMIN = {"Cookie": "session_token=test_session_admin_X"}
VIP = {"Cookie": "session_token=test_session_vip_X"}
VIP_UID = "user_test_vip01"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(os.environ["MONGO_URL"])
    d = client[os.environ["DB_NAME"]]
    yield d
    # cleanup TEST_ orders
    d.orders.delete_many({"order_number": {"$regex": "^TEST_ITER41_"}})


def _seed_order(db, delivery_method: str, status: str, amount_to: float = 25000):
    oid = f"TEST_ITER41_{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "order_id": oid,
        "id": oid,
        "order_number": oid,
        "user_id": VIP_UID,
        "from_code": "USDT",
        "to_code": "CUP",
        "amount_from": 100.0,
        "amount_to": amount_to,
        "rate_applied": 250.0,
        "delivery_method": delivery_method,
        "status": status,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    db.orders.insert_one(doc)
    return oid


def _get_cup_row(rows):
    return next((r for r in rows if r["currency"] == "CUP"), None)


def test_company_funds_shape_and_outflow_orders_field(db):
    r = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and len(data) > 0
    row = data[0]
    for f in ["currency", "inflow", "outflow_orders", "outflow_clients",
              "outflow_company", "manual_inflow", "manual_outflow", "balance"]:
        assert f in row, f"missing field {f} in row {row}"


def test_completed_transfer_reduces_balance(db):
    baseline = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN).json()
    base_row = _get_cup_row(baseline) or {"outflow_orders": 0, "balance": 0}
    base_out = base_row.get("outflow_orders", 0)
    base_bal = base_row.get("balance", 0)

    _seed_order(db, "transfer", "completed", 25000)

    after = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN).json()
    row = _get_cup_row(after)
    assert row is not None
    assert row["outflow_orders"] == pytest.approx(base_out + 25000)
    assert row["balance"] == pytest.approx(base_bal - 25000)


def test_completed_accumulate_does_not_reduce(db):
    baseline = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN).json()
    base_row = _get_cup_row(baseline) or {"outflow_orders": 0, "balance": 0}
    base_out = base_row.get("outflow_orders", 0)
    base_bal = base_row.get("balance", 0)

    _seed_order(db, "accumulate", "completed", 25000)

    after = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN).json()
    row = _get_cup_row(after) or {"outflow_orders": 0, "balance": 0}
    assert row.get("outflow_orders", 0) == pytest.approx(base_out)
    assert row.get("balance", 0) == pytest.approx(base_bal)


def test_approved_not_completed_does_not_reduce(db):
    baseline = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN).json()
    base_row = _get_cup_row(baseline) or {"outflow_orders": 0}
    base_out = base_row.get("outflow_orders", 0)

    _seed_order(db, "transfer", "approved", 25000)

    after = requests.get(f"{BASE}/api/admin/company-funds", headers=ADMIN).json()
    row = _get_cup_row(after) or {"outflow_orders": 0}
    assert row.get("outflow_orders", 0) == pytest.approx(base_out)


def test_admin_transactions_shows_order_payout(db):
    oid = _seed_order(db, "transfer", "completed", 25000)
    r = requests.get(f"{BASE}/api/admin/transactions?direction=out", headers=ADMIN, timeout=15)
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body if isinstance(body, list) else [])
    match = [i for i in items if i.get("ref_type") == "order_payout"
             and i.get("currency") == "CUP" and i.get("amount") == 25000
             and i.get("method") == "transfer"]
    assert len(match) >= 1, f"no matching order_payout row found for {oid}"


def test_admin_transactions_accumulate_not_present(db):
    oid = _seed_order(db, "accumulate", "completed", 25000)
    r = requests.get(f"{BASE}/api/admin/transactions?direction=out", headers=ADMIN)
    body = r.json()
    items = body.get("items", body if isinstance(body, list) else [])
    match = [i for i in items if i.get("ref_id") == oid and i.get("ref_type") == "order_payout"]
    assert len(match) == 0, "accumulate must NOT emit order_payout"


def test_client_sees_own_payout():
    r = requests.get(f"{BASE}/api/me/transactions", headers=VIP, timeout=15)
    assert r.status_code == 200
    body = r.json()
    items = body.get("items", body if isinstance(body, list) else [])
    payouts = [i for i in items if i.get("ref_type") == "order_payout" and i.get("direction") == "out"]
    assert len(payouts) >= 1, "VIP should see at least one order_payout row"


def test_transactions_csv_export_contains_order_payout():
    r = requests.get(f"{BASE}/api/admin/transactions/export.csv", headers=ADMIN, timeout=20)
    assert r.status_code == 200
    body = r.text
    assert "order_payout" in body, "CSV export must contain order_payout string"


def test_rate_update_returns_200_and_fanout_survives(db):
    # find a rate
    rate = db.exchange_rates.find_one({}) or db.rates.find_one({})
    if not rate:
        pytest.skip("no rate seeded")
    rate_id = rate.get("id") or rate.get("rate_id") or str(rate.get("_id"))
    payload = {
        "from_code": rate["from_code"],
        "to_code": rate["to_code"],
        "rate_normal": (rate.get("rate_normal", 250.0) or 250.0) + 0.01,
        "rate_vip": rate.get("rate_vip", 255.0) or 255.0,
        "real_rate": rate.get("real_rate", 5.0) or 5.0,
        "totp_code": _totp(),
    }
    r = requests.put(f"{BASE}/api/admin/rates/{rate_id}", headers=_admin_headers(), json=payload, timeout=15)
    assert r.status_code in (200, 201), f"unexpected {r.status_code}: {r.text}"
    body = r.json()
    assert abs(float(body.get("rate_normal", 0)) - payload["rate_normal"]) < 0.001


def test_rate_update_noop_still_200(db):
    rate = db.exchange_rates.find_one({}) or db.rates.find_one({})
    if not rate:
        pytest.skip("no rate seeded")
    rate_id = rate.get("id") or rate.get("rate_id") or str(rate.get("_id"))
    payload = {
        "from_code": rate["from_code"],
        "to_code": rate["to_code"],
        "rate_normal": rate.get("rate_normal", 250.0),
        "rate_vip": rate.get("rate_vip", 255.0),
        "real_rate": rate.get("real_rate", 5.0) or 5.0,
        "totp_code": _totp(),
    }
    r = requests.put(f"{BASE}/api/admin/rates/{rate_id}", headers=_admin_headers(), json=payload, timeout=15)
    assert r.status_code in (200, 201)
