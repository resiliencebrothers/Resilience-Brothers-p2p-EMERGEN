"""iter145 — Daily inflow totals per collection account (reconciliation).

GET /api/admin/payment-accounts/daily-totals?days=N
- Buckets by UTC ISO day (created_at[:10]).
- confirmed = approved/completed orders + approved batch items.
- pending   = rows still in review. Rejected rows excluded entirely.
- Gated by `payment_accounts` permission (client → 403).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
ACC_ID = "payacc_totals_test"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(days_ago: int, hour: int = 12) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.replace(hour=hour, minute=0, second=0).isoformat()


def _day(days_ago: int) -> str:
    return _iso(days_ago)[:10]


@pytest.fixture(scope="module", autouse=True)
def _seed():
    db = _db()
    db.payment_accounts.insert_one({
        "id": ACC_ID, "currency_code": "ZTT", "label": "Zelle Totals Test",
        "account_details": "x", "min_amount": 50, "max_amount": None,
        "is_active": True, "created_at": _iso(30), "updated_at": _iso(30),
    })
    db.orders.insert_many([
        # today: one completed (100) + one pending (40)
        {"id": "ord_tt_1", "user_id": "u1", "from_code": "ZTT", "to_code": "CUP",
         "amount_from": 100, "amount_to": 1, "status": "completed",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(0)},
        {"id": "ord_tt_2", "user_id": "u1", "from_code": "ZTT", "to_code": "CUP",
         "amount_from": 40, "amount_to": 1, "status": "pending",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(0)},
        # yesterday: approved (60) + rejected (999, must NOT count)
        {"id": "ord_tt_3", "user_id": "u1", "from_code": "ZTT", "to_code": "CUP",
         "amount_from": 60, "amount_to": 1, "status": "approved",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(1)},
        {"id": "ord_tt_4", "user_id": "u1", "from_code": "ZTT", "to_code": "CUP",
         "amount_from": 999, "amount_to": 1, "status": "rejected",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(1)},
        # outside a 7-day window
        {"id": "ord_tt_5", "user_id": "u1", "from_code": "ZTT", "to_code": "CUP",
         "amount_from": 500, "amount_to": 1, "status": "completed",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(20)},
    ])
    db.vip_batch_items.insert_many([
        # today: approved batch item (70)
        {"id": "vit_tt_1", "batch_id": "b1", "vip_user_id": "v1",
         "from_code": "ZTT", "to_code": "CUP", "amount": 70, "status": "approved",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(0)},
        # today: rejected item (must NOT count)
        {"id": "vit_tt_2", "batch_id": "b1", "vip_user_id": "v1",
         "from_code": "ZTT", "to_code": "CUP", "amount": 555, "status": "rejected",
         "payment_account_id": ACC_ID, "payment_account_label": "Zelle Totals Test",
         "created_at": _iso(0)},
    ])
    yield
    db.payment_accounts.delete_many({"id": ACC_ID})
    db.orders.delete_many({"id": {"$regex": "^ord_tt_"}})
    db.vip_batch_items.delete_many({"id": {"$regex": "^vit_tt_"}})


def _rows(days=7):
    r = requests.get(f"{API}/admin/payment-accounts/daily-totals",
                     params={"days": days}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return [row for row in r.json()["rows"] if row["account_id"] == ACC_ID]


def test_daily_totals_math():
    rows = {r["date"]: r for r in _rows(7)}
    today, yday = rows[_day(0)], rows[_day(1)]
    # today: confirmed = 100 (order) + 70 (batch item); pending = 40
    assert today["confirmed"] == 170 and today["pending"] == 40
    assert today["total"] == 210
    assert today["count_confirmed"] == 2 and today["count_pending"] == 1
    assert today["label"] == "Zelle Totals Test"
    assert today["currency_code"] == "ZTT"
    # yesterday: approved 60 only — rejected 999 excluded
    assert yday["confirmed"] == 60 and yday["pending"] == 0
    assert yday["total"] == 60


def test_window_and_ordering():
    rows7 = _rows(7)
    assert all(r["date"] >= _day(6) for r in rows7)  # 20-day-old row excluded
    dates = [r["date"] for r in rows7]
    assert dates == sorted(dates, reverse=True)
    rows30 = _rows(30)
    assert any(r["date"] == _day(20) and r["confirmed"] == 500 for r in rows30)


def test_permission_gate():
    r = requests.get(f"{API}/admin/payment-accounts/daily-totals",
                     headers=_hdr(VIP_TOKEN))
    assert r.status_code == 403


def test_export_csv():
    r = requests.get(f"{API}/admin/payment-accounts/daily-totals/export.csv",
                     params={"days": 7}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "conciliacion_cuentas_" in r.headers.get("content-disposition", "")
    body = r.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith('"fecha","cuenta","moneda"')
    today_line = [ln for ln in body.splitlines()
                  if _day(0) in ln and "Zelle Totals Test" in ln]
    assert today_line and '"170.00"' in today_line[0] and '"40.00"' in today_line[0]


def test_export_csv_account_filter():
    r = requests.get(f"{API}/admin/payment-accounts/daily-totals/export.csv",
                     params={"days": 7, "account": "payacc_no_such"},
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    assert "Zelle Totals Test" not in r.content.decode("utf-8-sig")


def test_export_pdf():
    r = requests.get(f"{API}/admin/payment-accounts/daily-totals/export.pdf",
                     params={"days": 7, "account": ACC_ID},
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 2000


def test_export_permission_gate():
    for kind in ("csv", "pdf"):
        r = requests.get(
            f"{API}/admin/payment-accounts/daily-totals/export.{kind}",
            headers=_hdr(VIP_TOKEN))
        assert r.status_code == 403
