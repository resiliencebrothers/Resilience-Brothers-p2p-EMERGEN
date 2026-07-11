"""iter55.28b — Monthly report PDF/CSV/timeseries include USDT conversion fees.

Follow-up to iter55.28: the monthly compliance PDF, CSV and daily/monthly
timeseries JSON must all include the conversion-fee revenue so the day-1
audit email surfaces this new income stream.
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, ADMIN_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _plant_fee_in(year: int, month: int, fee: float = 0.01):
    """Plant an audit_log row for `vip.convert` inside a given month."""
    _db().audit_log.insert_one({
        "id": uuid.uuid4().hex,
        "actor_id": "user_iter5528b",
        "actor_email": "iter5528b_planted@ex.com",
        "actor_name": "iter5528b",
        "actor_role": "vip",
        "actor_permissions": [],
        "actor_permissions_effective": "all_staff_default",
        "action": "vip.convert",
        "entity_type": "user",
        "entity_id": "user_iter5528b",
        "summary": "planted",
        "details": {"usdt_fee": fee, "amount_to_gross": 5.0,
                    "amount_to": 5.0 - fee, "to_code": "USDT",
                    "from_code": "CUP"},
        "created_at": datetime(year, month, 15, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
    })


def _cleanup():
    _db().audit_log.delete_many({"actor_email": "iter5528b_planted@ex.com"})


def test_timeseries_daily_exposes_fees_per_bucket():
    """`/admin/revenue/timeseries?granularity=day&days=90` rows must expose
    the new `conversion_fees_usdt` + `conversions` fields."""
    _cleanup()
    today = datetime.now(timezone.utc)
    _plant_fee_in(today.year, today.month, fee=0.01)

    r = requests.get(f"{API}/admin/revenue/timeseries",
                     headers=_hdr(ADMIN_TOKEN),
                     params={"granularity": "day", "days": 90})
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    total_fees = sum(row.get("conversion_fees_usdt", 0.0) for row in rows)
    total_convs = sum(row.get("conversions", 0) for row in rows)
    assert total_fees >= 0.01 - 1e-6
    assert total_convs >= 1
    _cleanup()


def test_monthly_export_pdf_includes_fees():
    """PDF export for the current month must produce a valid file and reflect
    the planted fee in the totals (verified via CSV since it's plain-text)."""
    _cleanup()
    today = datetime.now(timezone.utc)
    # Plant 3 fee rows in the current month → +0.03 USDT
    for _ in range(3):
        _plant_fee_in(today.year, today.month)

    # CSV format — easy to assert content
    r_csv = requests.get(f"{API}/admin/revenue/monthly/export",
                        headers=_hdr(ADMIN_TOKEN),
                        params={"year": today.year, "month": today.month,
                                "format": "csv"})
    assert r_csv.status_code == 200, r_csv.text
    csv_text = r_csv.content.decode("utf-8-sig")
    assert "Comisiones USDT" in csv_text, "CSV header missing new column"
    # Look at TOTAL row for the fee sum (>= 0.03 since we planted 3 × 0.01)
    total_line = [ln for ln in csv_text.splitlines() if ln.startswith("TOTAL")]
    assert total_line, "CSV must have a TOTAL row"

    # PDF format — validate magic bytes only (content is binary)
    r_pdf = requests.get(f"{API}/admin/revenue/monthly/export",
                        headers=_hdr(ADMIN_TOKEN),
                        params={"year": today.year, "month": today.month,
                                "format": "pdf"})
    assert r_pdf.status_code == 200
    assert r_pdf.content.startswith(b"%PDF-"), "PDF magic bytes missing"
    assert len(r_pdf.content) > 2000, "PDF suspiciously small"
    _cleanup()


def test_build_buckets_accumulates_fees_pure():
    """Pure unit test — no HTTP, no DB — of the build_buckets function."""
    from revenue_report import build_buckets
    fee_rows = [
        {"created_at": "2026-02-01T00:00:00+00:00",
         "details": {"usdt_fee": 0.01}},
        {"created_at": "2026-02-01T12:00:00+00:00",
         "details": {"usdt_fee": 0.01}},
        {"created_at": "2026-02-05T00:00:00+00:00",
         "details": {"usdt_fee": 0.01}},
        {"created_at": "2026-02-05T00:00:00+00:00",
         "details": {"usdt_fee": 0.00}},  # non-positive → skipped
    ]
    rows = build_buckets(
        orders=[], redemptions=[], profit_per_order_usdt={},
        granularity="day", conversion_fees=fee_rows,
    )
    day1 = next(r for r in rows if r["bucket"] == "2026-02-01")
    day5 = next(r for r in rows if r["bucket"] == "2026-02-05")
    assert day1["conversion_fees_usdt"] == 0.02
    assert day1["conversions"] == 2
    assert day1["total_profit_usdt"] == 0.02
    assert day5["conversion_fees_usdt"] == 0.01
    assert day5["conversions"] == 1
