"""iter113 — Profitability Calculator backend tests (admin_profitability router)."""
import os
import requests
import pytest
from pymongo import MongoClient

BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
A = {"Authorization": "Bearer test_session_admin_X"}
E = {"Authorization": "Bearer test_session_employee_X"}
V = {"Authorization": "Bearer test_session_vip_X"}

_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(autouse=True)
def _cleanup_ops():
    yield
    # cleanup any TEST_ ops created
    _db.profitability_operations.delete_many({"client_name": {"$regex": "^TEST_"}})


# ---------- settings ----------
class TestSettings:
    def test_get_settings_requires_auth(self):
        r = requests.get(f"{BASE}/api/admin/profitability/settings")
        assert r.status_code in (401, 403)

    def test_get_settings_admin(self):
        r = requests.get(f"{BASE}/api/admin/profitability/settings", headers=A)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_put_settings_normalizes_currency(self):
        r = requests.put(
            f"{BASE}/api/admin/profitability/settings",
            headers=A,
            json={"items": [{"currency": "cup ", "buy_pct": 26, "sell_pct": 37}]},
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert any(i["currency"] == "CUP" and i["buy_pct"] == 26 and i["sell_pct"] == 37 for i in items)
        # verify persistence
        g = requests.get(f"{BASE}/api/admin/profitability/settings", headers=A).json()
        assert any(i["currency"] == "CUP" for i in g["items"])


# ---------- operations ----------
class TestOperations:
    def test_create_op_profitable(self):
        r = requests.post(
            f"{BASE}/api/admin/profitability/operations",
            headers=A,
            json={
                "client_name": "TEST_Profit", "currency": "USDT", "payment_currency": "CUP",
                "quantity": 2, "sell_price": 715, "buy_price": 740, "buy_pct": 26, "sell_pct": 37,
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["result_fx"] == -50
        assert abs(d["conversion_gain"] - 124.8413) < 0.01
        assert abs(d["net_gain"] - 74.8413) < 0.01
        assert abs(d["profitability_pct"] - 5.0568) < 0.01
        assert d["status"] == "profitable"

    def test_create_op_loss(self):
        r = requests.post(
            f"{BASE}/api/admin/profitability/operations",
            headers=A,
            json={
                "client_name": "TEST_Loss", "currency": "USDT", "payment_currency": "CUP",
                "quantity": 1, "sell_price": 700, "buy_price": 740, "buy_pct": 0, "sell_pct": 0,
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "loss"
        assert d["net_gain"] == -40

    def test_list_ops_sorted_with_totals(self):
        # create 2 ops
        for name in ("TEST_A", "TEST_B"):
            requests.post(f"{BASE}/api/admin/profitability/operations", headers=A, json={
                "client_name": name, "currency": "USDT", "payment_currency": "CUP",
                "quantity": 1, "sell_price": 715, "buy_price": 740, "buy_pct": 26, "sell_pct": 37,
            })
        r = requests.get(f"{BASE}/api/admin/profitability/operations", headers=A)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "totals" in d
        assert d["totals"]["count"] >= 2
        assert "net_by_currency" in d["totals"]
        # filter
        r2 = requests.get(f"{BASE}/api/admin/profitability/operations?status_q=profitable", headers=A)
        assert r2.status_code == 200
        assert all(i["status"] == "profitable" for i in r2.json()["items"])

    def test_delete_op(self):
        r = requests.post(f"{BASE}/api/admin/profitability/operations", headers=A, json={
            "client_name": "TEST_Del", "currency": "USDT", "payment_currency": "CUP",
            "quantity": 1, "sell_price": 715, "buy_price": 740, "buy_pct": 26, "sell_pct": 37,
        })
        op_id = r.json()["id"]
        d = requests.delete(f"{BASE}/api/admin/profitability/operations/{op_id}", headers=A)
        assert d.status_code == 200
        assert d.json()["ok"] is True

    def test_delete_op_404(self):
        r = requests.delete(f"{BASE}/api/admin/profitability/operations/nonexistent-id-xyz", headers=A)
        assert r.status_code == 404


# ---------- permission gating ----------
class TestPermissionGating:
    def test_vip_forbidden(self):
        r = requests.get(f"{BASE}/api/admin/profitability/settings", headers=V)
        assert r.status_code == 403

    def test_employee_default_allowed(self):
        # ensure empty allowed_permissions
        _db.users.update_one({"user_id": "user_test_employee01"}, {"$set": {"allowed_permissions": []}})
        r = requests.get(f"{BASE}/api/admin/profitability/settings", headers=E)
        assert r.status_code == 200, r.text

    def test_employee_scoped_blocked(self):
        _db.users.update_one({"user_id": "user_test_employee01"}, {"$set": {"allowed_permissions": ["orders"]}})
        try:
            r = requests.get(f"{BASE}/api/admin/profitability/settings", headers=E)
            assert r.status_code == 403
            # error message mentions the feature
            body = r.text
            assert "Rentabilidad" in body or "profitability" in body.lower()
        finally:
            _db.users.update_one({"user_id": "user_test_employee01"}, {"$set": {"allowed_permissions": []}})


# ---------- catalog ----------
class TestCatalog:
    def test_catalog_includes_profitability(self):
        r = requests.get(f"{BASE}/api/admin/permissions/catalog", headers=A)
        assert r.status_code == 200, r.text
        d = r.json()
        # catalog could be list of items or a dict
        items = d if isinstance(d, list) else d.get("items", d.get("permissions", []))
        codes = [i.get("code") for i in items]
        assert "profitability" in codes
        p = next(i for i in items if i.get("code") == "profitability")
        assert p.get("label") == "Cálculo de Rentabilidad"


# ---------- regression ----------
class TestRegression:
    def test_company_funds_still_works(self):
        r = requests.get(f"{BASE}/api/admin/company-funds", headers=A)
        assert r.status_code == 200
