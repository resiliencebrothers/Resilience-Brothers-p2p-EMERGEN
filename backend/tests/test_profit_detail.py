"""iter142 — Profit Detail drill-down endpoint tests.

Coverage:
 1. Sums per-row `profit` and returns `profit_total = orders + batches` matching
    the number shown on the "Rentabilidad total" chip.
 2. Only orders whose `to_code` matches the currency are included.
 3. Only VIP batch items whose `from_code` matches are included.
 4. Employee currency scope is enforced (403 for out-of-scope currency).
 5. Orders without a real_rate configured are skipped (parity with the
    aggregate — same math as `_aggregate_profit_by_currency`).
"""
import os
import requests
import pytest
from pymongo import MongoClient

BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
A = {"Authorization": "Bearer test_session_admin_X"}
E_SCOPED = {"Authorization": "Bearer test_session_employee_X"}
V = {"Authorization": "Bearer test_session_vip_X"}

_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

NOTE = "profit_detail_test"


@pytest.fixture(autouse=True)
def _cleanup():
    _db.orders.delete_many({"note_marker": NOTE})
    _db.vip_batch_items.delete_many({"_marker": NOTE})
    _db.rates.delete_many({"_marker": NOTE})
    yield
    _db.orders.delete_many({"note_marker": NOTE})
    _db.vip_batch_items.delete_many({"_marker": NOTE})
    _db.rates.delete_many({"_marker": NOTE})


def _plant_rate(fc: str, tc: str, real: float, applied: float):
    _db.rates.insert_one({
        "id": f"rate_{fc}_{tc}_{NOTE}", "from_code": fc, "to_code": tc,
        "real_rate": real, "rate_normal": applied, "rate_vip": applied,
        "_marker": NOTE,
    })


def _plant_order(oid: str, fc: str, tc: str, amount_from: float,
                 amount_to: float, status: str = "approved"):
    _db.orders.insert_one({
        "id": oid, "from_code": fc, "to_code": tc,
        "amount_from": amount_from, "amount_to": amount_to,
        "status": status, "user_id": "user_test_vip01",
        "user_email": "vip.test@resilience.com", "user_name": "VIP Tester",
        "user_role": "vip", "delivery_method": "cash",
        "created_at": "2026-08-01T12:00:00+00:00",
        "updated_at": "2026-08-01T13:00:00+00:00",
        "note_marker": NOTE,
    })


def _plant_batch_item(iid: str, fc: str, tc: str, amount: float,
                      amount_to: float, applied_rate: float):
    _db.vip_batch_items.insert_one({
        "id": iid, "batch_id": f"batch_{iid}",
        "vip_user_id": "user_test_vip01",
        "from_code": fc, "to_code": tc,
        "amount": amount, "amount_to": amount_to,
        "rate_applied": applied_rate, "status": "approved",
        "card_number": "9212 9598 7274 4356",
        "holder_name": "9212 9598 7274 4356",
        "reviewed_at": "2026-08-01T14:00:00+00:00",
        "created_at": "2026-08-01T12:30:00+00:00",
        "_marker": NOTE,
    })


class TestProfitDetailEndpoint:
    def test_requires_auth(self):
        r = requests.get(f"{BASE}/api/admin/company-funds/profit-detail/CUP")
        assert r.status_code in (401, 403)

    def test_orders_and_batches_sum_to_profit_total(self):
        # BRL pair: real 5.0, applied 4.5 → order sends 100 USDT, receives 450 BRL.
        # Profit_to = 100 * 5 - 450 = 50 BRL (order profit in to_code BRL).
        _plant_rate("USDT", "BRL", real=5.0, applied=4.5)
        _plant_order("test_ord_brl_1", "USDT", "BRL",
                      amount_from=100.0, amount_to=450.0)

        # BRL as from_code in a VIP batch: real 20, applied 18 → sends 200 BRL,
        # receives 3600 CUP. margin_from = 200 * (20-18)/20 = 20 BRL.
        _plant_rate("BRL", "CUP", real=20.0, applied=18.0)
        _plant_batch_item("test_bat_brl_1", "BRL", "CUP",
                          amount=200.0, amount_to=3600.0, applied_rate=18.0)

        r = requests.get(
            f"{BASE}/api/admin/company-funds/profit-detail/BRL", headers=A,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["currency"] == "BRL"
        # orders_profit_total sums P2P orders with to_code=BRL only.
        # batches_profit_total sums VIP batch margins with from_code=BRL only.
        assert any(o["id"] == "test_ord_brl_1" for o in d["orders"])
        assert any(b["id"] == "test_bat_brl_1" for b in d["batches"])
        # Row-level profit checks.
        ord_row = next(o for o in d["orders"] if o["id"] == "test_ord_brl_1")
        assert ord_row["profit"] == 50.0
        bat_row = next(b for b in d["batches"] if b["id"] == "test_bat_brl_1")
        assert round(bat_row["profit"], 4) == 20.0
        # Total is the sum.
        assert round(d["orders_profit_total"], 4) >= 50.0
        assert round(d["batches_profit_total"], 4) >= 20.0
        assert round(d["profit_total"], 4) == round(
            d["orders_profit_total"] + d["batches_profit_total"], 4,
        )

    def test_only_matching_currency_included(self):
        # Plant a USDT→EUR order (to_code=EUR). It must NOT appear in the BRL
        # breakdown — cross-currency isolation is critical for the audit trail.
        _plant_rate("USDT", "EUR", real=1.10, applied=1.05)
        _plant_order("test_ord_eur_1", "USDT", "EUR",
                      amount_from=100.0, amount_to=105.0)

        r = requests.get(
            f"{BASE}/api/admin/company-funds/profit-detail/BRL", headers=A,
        )
        assert r.status_code == 200
        d = r.json()
        assert not any(o["id"] == "test_ord_eur_1" for o in d["orders"])

    def test_orders_without_real_rate_skipped(self):
        # No rate configured for the synthetic ZZT currency → order must be
        # skipped just like the aggregate does (silent skip, not an error).
        # Uses a code that no other test/seed ever plants a rate for, so the
        # premise holds even on a polluted test DB.
        _plant_order("test_ord_zzt_norate", "USDT", "ZZT",
                      amount_from=100.0, amount_to=1800.0)
        r = requests.get(
            f"{BASE}/api/admin/company-funds/profit-detail/ZZT", headers=A,
        )
        assert r.status_code == 200
        d = r.json()
        assert not any(o["id"] == "test_ord_zzt_norate" for o in d["orders"])

    def test_employee_scope_blocks_out_of_scope_currency(self):
        # Sanity-check: the endpoint must respect `allowed_currencies`. If the
        # test employee has a scope AND our currency is out of it → 403.
        emp = _db.users.find_one({"user_id": "user_test_employee01"}) or {}
        allowed = emp.get("allowed_currencies") or []
        if not allowed:
            pytest.skip("test employee has no currency scope configured")
        forbidden = next(
            (code for code in ("BRL", "MXN", "EUR", "USDT")
             if code.upper() not in [c.upper() for c in allowed]),
            None,
        )
        if not forbidden:
            pytest.skip("no forbidden currency to test scope enforcement")
        r = requests.get(
            f"{BASE}/api/admin/company-funds/profit-detail/{forbidden}",
            headers=E_SCOPED,
        )
        assert r.status_code == 403

    def test_client_forbidden(self):
        r = requests.get(
            f"{BASE}/api/admin/company-funds/profit-detail/BRL", headers=V,
        )
        assert r.status_code == 403

    def test_invalid_currency_400(self):
        r = requests.get(
            f"{BASE}/api/admin/company-funds/profit-detail/%20", headers=A,
        )
        # Whitespace-only code normalises to None → 400.
        assert r.status_code == 400
