"""iter88 — Company funds CSV export."""
import io
import csv
import os
import pytest
import requests
from pymongo import MongoClient
from datetime import datetime, timezone

from conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def seeded_movements():
    """Seed a known handful of adjustments and withdrawals, then clean up."""
    db = _db()
    ids = []
    now = datetime.now(timezone.utc).isoformat()
    # 2 adjustments (inflow + outflow) and 2 company withdrawals.
    for i, (kind, amount, currency, name, adj_type) in enumerate([
        ("adj", 5000, "USD", "Owner Alice", "inflow"),
        ("adj", 200,  "USD", "Cash box",    "outflow"),
    ]):
        _id = f"iter88_adj_{i}"
        db.company_fund_adjustments.insert_one({
            "id": _id,
            "adjustment_type": adj_type,
            "currency": currency,
            "amount": amount,
            "method": "cash",
            "source_name": name,
            "source_account": "",
            "note": f"iter88 seed {i}",
            "actor_id": "user_test_admin01",
            "actor_email": "admin.test@resilience.com",
            "actor_name": "Admin Test",
            "created_at": now,
        })
        ids.append(("adj", _id))
    for i, (amt, beneficiary, status) in enumerate([
        (1500, "Iter88 Vendor A", "paid"),
        (50,   "Iter88 Vendor B", "pending"),
    ]):
        _id = f"iter88_cw_{i}"
        db.company_withdrawals.insert_one({
            "id": _id,
            "amount": amt,
            "currency": "USD",
            "beneficiary": beneficiary,
            "authorized_by_id": "user_test_admin01",
            "authorized_by_name": "Admin Test",
            "authorized_by_email": "admin.test@resilience.com",
            "concept": f"iter88 seed {i}",
            "invoice_image": "",
            "note": "",
            "status": status,
            "created_at": now,
        })
        ids.append(("cw", _id))
    yield ids
    for kind, _id in ids:
        col = db.company_fund_adjustments if kind == "adj" else db.company_withdrawals
        col.delete_one({"id": _id})


def _parse_csv(text: str) -> list[dict]:
    # utf-8-sig prepends a BOM; strip it so DictReader sees a clean header row.
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return list(csv.DictReader(io.StringIO(text)))


def test_export_csv_includes_seeded_movements(seeded_movements):
    r = requests.get(
        f"{BASE_URL}/api/admin/company-funds/export.csv",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert ct.startswith("text/csv"), ct
    rows = _parse_csv(r.text)
    # Must include the 4 seeded IDs.
    ids = {row["id"] for row in rows}
    assert "iter88_adj_0" in ids
    assert "iter88_adj_1" in ids
    assert "iter88_cw_0" in ids
    assert "iter88_cw_1" in ids
    # Headers present and stable.
    assert set(rows[0].keys()) >= {
        "created_at", "movement_kind", "direction", "currency",
        "amount", "party", "method", "concept_or_note", "status",
        "authorized_by", "id",
    }


def test_export_csv_signs_correctly(seeded_movements):
    r = requests.get(
        f"{BASE_URL}/api/admin/company-funds/export.csv",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30,
    )
    assert r.status_code == 200
    rows = {row["id"]: row for row in _parse_csv(r.text)}
    # Adjustments: inflow → positive, outflow → negative.
    assert float(rows["iter88_adj_0"]["amount"]) > 0
    assert rows["iter88_adj_0"]["direction"] == "inflow"
    assert float(rows["iter88_adj_1"]["amount"]) < 0
    assert rows["iter88_adj_1"]["direction"] == "outflow"
    # Company withdrawals: paid → negative, pending → positive (still owed).
    assert float(rows["iter88_cw_0"]["amount"]) < 0
    assert rows["iter88_cw_0"]["status"] == "paid"
    assert float(rows["iter88_cw_1"]["amount"]) > 0
    assert rows["iter88_cw_1"]["status"] == "pending"


def test_export_csv_currency_filter(seeded_movements):
    # All seeds are USD — filtering to USD keeps everything.
    r = requests.get(
        f"{BASE_URL}/api/admin/company-funds/export.csv?currency=USD",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30,
    )
    assert r.status_code == 200
    rows = _parse_csv(r.text)
    assert all(row["currency"] == "USD" for row in rows)
    # Filtering to a currency we didn't seed → seeded IDs are gone.
    r2 = requests.get(
        f"{BASE_URL}/api/admin/company-funds/export.csv?currency=CUP",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30,
    )
    assert r2.status_code == 200
    rows2 = _parse_csv(r2.text)
    ids2 = {row["id"] for row in rows2}
    assert not (ids2 & {"iter88_adj_0", "iter88_adj_1", "iter88_cw_0", "iter88_cw_1"})


def test_export_csv_forbidden_for_client():
    r = requests.get(
        f"{BASE_URL}/api/admin/company-funds/export.csv",
        headers={"Authorization": f"Bearer {VIP_TOKEN}"},
        timeout=30,
    )
    # 403 — VIP does not have company_funds permission.
    assert r.status_code in (401, 403)


def test_export_csv_invalid_date():
    r = requests.get(
        f"{BASE_URL}/api/admin/company-funds/export.csv?since=not-a-date",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30,
    )
    assert r.status_code == 400
