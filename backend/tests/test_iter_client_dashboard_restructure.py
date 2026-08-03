"""
Backend tests for client-dashboard restructure (iter120):
- GET /api/me/transactions: order/order_payout/vip_batch_item rows include
  from_code, to_code, amount_from, amount_to.
- Conversion rows keep their fields.
- Filters (direction, currency), CSV+PDF exports, X-Total-Count header.
- GET /api/admin/transactions: still works (regression) via admin session.

No hardcoded secrets: session tokens are generated per run (uuid) and the
DB rows are cleaned up on teardown. Env (MONGO_URL, DB_NAME,
REACT_APP_BACKEND_URL) is loaded by tests/conftest.py.
"""
import os
import uuid
import datetime as dt

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")


def _open_session(user_id: str):
    """Insert a fresh user_sessions row for `user_id` with a random token."""
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    token = f"test_session_{uuid.uuid4().hex}"
    now = dt.datetime.now(dt.timezone.utc)
    db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (now + dt.timedelta(hours=2)).isoformat(),
        "created_at": now.isoformat(),
    })
    return client, db, token


def _session_fixture(user_id: str):
    client, db, token = _open_session(user_id)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    yield s
    db.user_sessions.delete_one({"session_token": token})
    client.close()


@pytest.fixture(scope="module")
def vip_session():
    yield from _session_fixture("user_test_vip01")


@pytest.fixture(scope="module")
def admin_session():
    yield from _session_fixture("user_test_admin01")


# ---------- /api/me/transactions ----------

def test_me_transactions_returns_items(vip_session):
    r = vip_session.get(f"{BASE_URL}/api/me/transactions", params={"limit": 100})
    assert r.status_code == 200, r.text
    assert "X-Total-Count" in r.headers, "X-Total-Count header must be present"
    data = r.json()
    assert isinstance(data, dict) and "items" in data, f"unexpected payload: {data}"
    assert isinstance(data["items"], list)
    # VIP has orders + conversions, so should have items
    assert len(data["items"]) > 0, "VIP should have transactions"


def test_order_rows_include_pair_fields(vip_session):
    r = vip_session.get(f"{BASE_URL}/api/me/transactions", params={"limit": 200})
    assert r.status_code == 200
    items = r.json()["items"]
    target_types = {"order", "order_payout", "vip_batch_item"}
    target_rows = [it for it in items if it.get("ref_type") in target_types]
    if not target_rows:
        pytest.skip("No order/order_payout/vip_batch_item rows for VIP user")
    for row in target_rows:
        for f in ("from_code", "to_code", "amount_from", "amount_to"):
            assert f in row, f"row {row.get('ref_type')}/{row.get('id')} missing field {f}: {row}"
        # types
        assert row["from_code"] is None or isinstance(row["from_code"], str)
        assert row["to_code"] is None or isinstance(row["to_code"], str)


def test_conversion_rows_still_have_fields(vip_session):
    r = vip_session.get(f"{BASE_URL}/api/me/transactions", params={"direction": "conversion", "limit": 100})
    assert r.status_code == 200
    items = r.json()["items"]
    if not items:
        pytest.skip("No conversion rows")
    for row in items:
        # Conversions should have from_code/to_code/amount_from/amount_to
        assert "from_code" in row and "to_code" in row
        assert "amount_from" in row and "amount_to" in row


def test_direction_filter_in_out(vip_session):
    for direction in ("in", "out"):
        r = vip_session.get(f"{BASE_URL}/api/me/transactions", params={"direction": direction, "limit": 50})
        assert r.status_code == 200, f"direction={direction} failed: {r.text}"


def test_currency_filter(vip_session):
    r = vip_session.get(f"{BASE_URL}/api/me/transactions", params={"currency": "USDT", "limit": 50})
    assert r.status_code == 200


def test_csv_export(vip_session):
    r = vip_session.get(f"{BASE_URL}/api/me/transactions/export.csv")
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert "csv" in ct.lower() or "text" in ct.lower(), f"unexpected content-type {ct}"
    # First line should look like a CSV header
    text = r.text
    assert "," in text.splitlines()[0]


def test_pdf_export(vip_session):
    r = vip_session.get(f"{BASE_URL}/api/me/transactions/export.pdf")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF", "PDF export should start with %PDF"


# ---------- /api/admin/transactions regression ----------

def test_admin_transactions_no_regression(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/admin/transactions", params={"limit": 20})
    assert r.status_code == 200, r.text
    data = r.json()
    # Should be a dict with items or list
    if isinstance(data, dict):
        assert "items" in data
        assert isinstance(data["items"], list)
    else:
        assert isinstance(data, list)
