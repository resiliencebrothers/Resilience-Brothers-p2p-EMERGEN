"""iter55.15 — Regression: company_fund_adjustments + company_withdrawals must
show up in /admin/transactions register.

Bug reported by operator on production:
  Admin registered an inflow of +10,000,000 CUPT via /admin/company-funds
  (Ajuste manual). The Fondo Empresa view correctly showed the capital
  balance, but /admin/transactions showed 'Entradas +0 CUPT' because
  build_transactions() did not consult the company_fund_adjustments
  collection.

This suite plants documents directly into `company_fund_adjustments` and
`company_withdrawals`, calls the admin transactions endpoint, and verifies
the entries surface in the register (with correct direction + amount).

It also verifies the /me/transactions endpoint DOES NOT expose these
company-level entries (they belong to the company, not to any individual
client).
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
TEST_TAG = "iter55_15_regression"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _cleanup():
    """Remove any residual planted documents from prior test runs."""
    db = _sync_db()
    db.company_fund_adjustments.delete_many({"note": TEST_TAG})
    db.company_withdrawals.delete_many({"note": TEST_TAG})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _plant_adjustment(adjustment_type: str, currency: str, amount: float,
                      source_name: str = "Socio X", method: str = "transfer") -> str:
    aid = str(uuid.uuid4())
    _sync_db().company_fund_adjustments.insert_one({
        "id": aid,
        "adjustment_type": adjustment_type,
        "currency": currency,
        "amount": amount,
        "method": method,
        "source_name": source_name,
        "source_account": "",
        "note": TEST_TAG,
        "actor_id": "user_test_admin01",
        "actor_email": "admin@test.com",
        "actor_name": "Admin Test",
        "created_at": _iso_now(),
    })
    return aid


def _plant_company_withdrawal(currency: str, amount: float, beneficiary: str,
                              status: str = "paid") -> str:
    cwid = str(uuid.uuid4())
    _sync_db().company_withdrawals.insert_one({
        "id": cwid,
        "amount": amount,
        "currency": currency,
        "beneficiary": beneficiary,
        "authorized_by_id": "user_test_admin01",
        "authorized_by_name": "Admin Test",
        "authorized_by_email": "admin@test.com",
        "concept": "Test expense",
        "invoice_image": "",
        "note": TEST_TAG,
        "status": status,
        "created_at": _iso_now(),
    })
    return cwid


# ============================================================
# 1. Bug reproducer — aporte propio should now appear as entrada
# ============================================================

def test_aporte_propio_shows_as_entrada_in_admin_transactions():
    _cleanup()
    _plant_adjustment("inflow", "CUPT", 10_000_000, source_name="Aporte del socio")

    r = requests.get(
        f"{API}/admin/transactions",
        headers=_hdr(ADMIN_TOKEN),
        params={"currency": "CUPT", "direction": "in"},
    )
    assert r.status_code == 200, r.text
    d = r.json()

    # The aporte should be present with the correct amount + direction + ref_type
    aportes = [t for t in d["items"]
               if t["ref_type"] == "company_adjustment" and t["currency"] == "CUPT"]
    assert len(aportes) >= 1, f"Expected the aporte to appear, got items: {d['items']}"
    a = aportes[0]
    assert a["direction"] == "in"
    assert a["amount"] == 10_000_000
    assert a["holder_name"] == "Aporte del socio"
    assert a["status"] == "approved"

    # Totals must reflect the aporte
    totals = d["totals"]["by_currency"]
    assert "CUPT" in totals
    assert totals["CUPT"]["in"] >= 10_000_000, f"Totals CUPT in={totals['CUPT']['in']}"


# ============================================================
# 2. Outflow (retiro manual de capital) shows as salida
# ============================================================

def test_manual_outflow_shows_as_salida():
    _cleanup()
    _plant_adjustment("outflow", "CUP", 500_000, source_name="Retiro operativo")

    r = requests.get(
        f"{API}/admin/transactions",
        headers=_hdr(ADMIN_TOKEN),
        params={"currency": "CUP", "direction": "out"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    outs = [t for t in d["items"]
            if t["ref_type"] == "company_adjustment" and t["currency"] == "CUP"]
    assert len(outs) >= 1
    o = outs[0]
    assert o["direction"] == "out"
    assert o["amount"] == 500_000


# ============================================================
# 3. Company withdrawal (retiro del fondo) shows as salida
# ============================================================

def test_company_withdrawal_shows_as_salida():
    _cleanup()
    _plant_company_withdrawal("USDT", 250.0, "Proveedor Y")

    r = requests.get(
        f"{API}/admin/transactions",
        headers=_hdr(ADMIN_TOKEN),
        params={"currency": "USDT", "direction": "out"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    withs = [t for t in d["items"]
             if t["ref_type"] == "company_withdrawal" and t["currency"] == "USDT"]
    assert len(withs) >= 1
    w = withs[0]
    assert w["direction"] == "out"
    assert w["amount"] == 250.0
    assert w["holder_name"] == "Proveedor Y"


# ============================================================
# 4. Pending company_withdrawals must NOT show (only approved/paid do)
# ============================================================

def test_pending_company_withdrawal_hidden():
    _cleanup()
    _plant_company_withdrawal("EUR", 999.0, "Should Not Appear", status="pending")

    r = requests.get(
        f"{API}/admin/transactions",
        headers=_hdr(ADMIN_TOKEN),
        params={"currency": "EUR"},
    )
    assert r.status_code == 200
    d = r.json()
    hits = [t for t in d["items"]
            if t["ref_type"] == "company_withdrawal" and t["holder_name"] == "Should Not Appear"]
    assert len(hits) == 0, "pending company_withdrawals must NOT show in the register"


# ============================================================
# 5. Filters (currency + holder + direction) work correctly
# ============================================================

def test_filters_work_on_company_adjustments():
    _cleanup()
    _plant_adjustment("inflow", "CUPT", 1_000_000, source_name="Alice")
    _plant_adjustment("inflow", "CUP", 200_000, source_name="Bob")

    # Filter by currency=CUPT should only return Alice
    r = requests.get(
        f"{API}/admin/transactions",
        headers=_hdr(ADMIN_TOKEN),
        params={"currency": "CUPT", "direction": "in"},
    )
    hits = [t for t in r.json()["items"]
            if t["ref_type"] == "company_adjustment"]
    assert any(t["holder_name"] == "Alice" for t in hits)
    assert not any(t["holder_name"] == "Bob" for t in hits)

    # Filter by holder=Bob should return only Bob's
    r2 = requests.get(
        f"{API}/admin/transactions",
        headers=_hdr(ADMIN_TOKEN),
        params={"holder": "Bob"},
    )
    hits2 = [t for t in r2.json()["items"]
             if t["ref_type"] == "company_adjustment"]
    assert any(t["holder_name"] == "Bob" for t in hits2)
    assert not any(t["holder_name"] == "Alice" for t in hits2)


# ============================================================
# 6. Scope isolation — /me/transactions must NEVER show company-level events
# ============================================================

def test_me_transactions_does_not_show_company_events():
    _cleanup()
    _plant_adjustment("inflow", "CUPT", 5_000_000, source_name="Company only")
    _plant_company_withdrawal("USDT", 100, "Not for me", status="paid")

    r = requests.get(f"{API}/me/transactions", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200
    items = r.json()["items"]
    assert not any(t["ref_type"] == "company_adjustment" for t in items)
    assert not any(t["ref_type"] == "company_withdrawal" for t in items)
