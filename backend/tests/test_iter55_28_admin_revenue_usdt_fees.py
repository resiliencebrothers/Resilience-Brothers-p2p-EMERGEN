"""iter55.28 — Admin Revenue exposes conversion-fees revenue (USDT).

The 0.01 USDT flat fee introduced in iter55.27 (fiat → USDT conversion) is
Resilience's own income. It is stored in `audit_log` with
`action == "vip.convert"` and `details.usdt_fee > 0`.

`GET /admin/revenue` must:
- Include `conversion_fees_usdt` (sum of all `details.usdt_fee` in period).
- Include `conversion_fees_count` (number of qualifying audit rows).
- Reflect the sum in `total_profit_usdt`.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, ADMIN_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _cleanup():
    _db().audit_log.delete_many({"actor_email": {"$regex": "^iter5528_"}})


def _plant_convert_audit(email: str, fee: float, days_ago: int = 0):
    """Insert an audit_log row that mimics a /vip/convert with a USDT fee."""
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    _db().audit_log.insert_one({
        "id": uuid.uuid4().hex,
        "actor_id": f"user_{email}",
        "actor_email": email,
        "actor_name": "iter55.28 planted",
        "actor_role": "vip",
        "actor_permissions": [],
        "actor_permissions_effective": "all_staff_default",
        "action": "vip.convert",
        "entity_type": "user",
        "entity_id": f"user_{email}",
        "summary": "planted",
        "details": {
            "from_code": "CUP",
            "to_code": "USDT",
            "amount_from": 100.0,
            "amount_to_gross": 3.0,
            "amount_to": 3.0 - fee,
            "rate": 0.03,
            "usdt_fee": fee,
        },
        "created_at": created,
    })


def test_revenue_endpoint_reports_conversion_fees():
    _cleanup()
    _plant_convert_audit("iter5528_a@ex.com", 0.01, days_ago=1)
    _plant_convert_audit("iter5528_b@ex.com", 0.01, days_ago=2)
    _plant_convert_audit("iter5528_c@ex.com", 0.01, days_ago=3)

    r = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()

    assert "conversion_fees_usdt" in body, "New field missing"
    assert "conversion_fees_count" in body, "New count field missing"
    # We planted 3 rows of 0.01; the total may include pre-existing rows too.
    assert body["conversion_fees_usdt"] >= 0.03 - 1e-6
    assert body["conversion_fees_count"] >= 3

    _cleanup()


def test_total_profit_includes_conversion_fees():
    """`total_profit_usdt` must aggregate p2p + marketplace + conversion fees."""
    _cleanup()
    r0 = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN))
    assert r0.status_code == 200
    b0 = r0.json()
    baseline_total = b0["total_profit_usdt"]
    baseline_fees = b0["conversion_fees_usdt"]

    # Plant 5 fees of 0.01 → +0.05
    for i in range(5):
        _plant_convert_audit(f"iter5528_x{i}@ex.com", 0.01, days_ago=0)

    r1 = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN))
    assert r1.status_code == 200
    b1 = r1.json()

    # Fee delta must be 0.05 (± tiny)
    delta_fees = b1["conversion_fees_usdt"] - baseline_fees
    assert abs(delta_fees - 0.05) < 1e-4, f"Fee delta {delta_fees} expected 0.05"

    # Total profit delta must include the fee delta
    delta_total = b1["total_profit_usdt"] - baseline_total
    assert abs(delta_total - 0.05) < 1e-4, f"Total delta {delta_total} expected 0.05"

    _cleanup()


def test_revenue_period_filter_scopes_fees():
    """days=7 excludes fee rows planted more than 7 days ago."""
    _cleanup()
    _plant_convert_audit("iter5528_recent@ex.com", 0.01, days_ago=1)
    _plant_convert_audit("iter5528_old@ex.com", 0.01, days_ago=60)

    r = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN),
                     params={"days": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    # Old fee must not be counted in the 7-day window; only recent one is added.
    # We compare vs a baseline where both are excluded to avoid coupling to prod data:
    _cleanup()
    r0 = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN),
                     params={"days": 7})
    assert r0.status_code == 200
    b0 = r0.json()

    # Now plant only the recent one and re-check delta
    _plant_convert_audit("iter5528_recent@ex.com", 0.01, days_ago=1)
    r1 = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN),
                     params={"days": 7})
    b1 = r1.json()
    assert abs((b1["conversion_fees_usdt"] - b0["conversion_fees_usdt"]) - 0.01) < 1e-4

    # Plant the old one too — the 7d filter must exclude it
    _plant_convert_audit("iter5528_old@ex.com", 0.01, days_ago=60)
    r2 = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN),
                     params={"days": 7})
    b2 = r2.json()
    assert abs(b2["conversion_fees_usdt"] - b1["conversion_fees_usdt"]) < 1e-4, \
        "Old fee (>7d) must NOT be counted"

    _cleanup()


def test_admin_only():
    """Non-admins cannot access the endpoint."""
    from tests.conftest import NORMAL_TOKEN
    r = requests.get(f"{API}/admin/revenue", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 403
