"""IPV Fase 1 — iter329 API-level tests for cutoff-report endpoint & CSV.

Verifies: permissions (products), invalid dates, start>date → 400, CSV headers
and TOTALES row, order by value DESC, count fields persisted in POST
/api/admin/inventory/counts (reference_cost, difference_value, currency).
"""
import os
import uuid
import csv
import io
import requests
import pytest
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

ADMIN = {"session_token": "test_session_admin_X"}
EMP = {"session_token": "test_session_employee_X"}
VIP = {"session_token": "test_session_vip_X"}
NORMAL = {"session_token": "test_session_normal_X"}


def _mov(pid, name, mtype, qty, created_at, unit_cost=0.0, unit_price=0.0):
    return {
        "id": str(uuid.uuid4()), "product_id": pid, "product_name": name,
        "type": mtype, "quantity": int(qty), "unit_cost": float(unit_cost),
        "unit_price": float(unit_price), "total": 0.0, "cost_of_sale": 0.0,
        "profit": 0.0, "note": "", "source": "manual", "ref_id": "",
        "created_at": created_at,
    }


@pytest.fixture
def two_products():
    """Create two isolated products with movements for ordering test."""
    pid1 = f"TEST_IPV329A_{uuid.uuid4().hex[:8]}"
    pid2 = f"TEST_IPV329B_{uuid.uuid4().hex[:8]}"
    _db.products.insert_many([
        {"id": pid1, "name": "TEST_HighValue", "category": "Prueba",
         "is_active": True, "stock": 10, "cost_usd": 100.0,
         "price_usd": 150.0, "owner_id": ""},
        {"id": pid2, "name": "TEST_LowValue", "category": "Prueba",
         "is_active": True, "stock": 5, "cost_usd": 10.0,
         "price_usd": 20.0, "owner_id": ""},
    ])
    # Both have an entry prior to cutoff 2026-09-10.
    _db.inventory_movements.insert_many([
        _mov(pid1, "TEST_HighValue", "entrada", 10,
             "2026-09-05T12:00:00+00:00", unit_cost=100.0),
        _mov(pid2, "TEST_LowValue", "entrada", 5,
             "2026-09-05T12:00:00+00:00", unit_cost=10.0),
    ])
    yield pid1, pid2
    for pid in (pid1, pid2):
        _db.products.delete_one({"id": pid})
        _db.inventory_movements.delete_many({"product_id": pid})
        _db.inventory_counts.delete_many({"product_id": pid})


# ──────────────────── Permissions ────────────────────
class TestPermissions:
    def test_admin_200(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10"}, cookies=ADMIN)
        assert r.status_code == 200, r.text

    def test_employee_200(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10"}, cookies=EMP)
        assert r.status_code == 200, r.text

    def test_vip_forbidden(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10"}, cookies=VIP)
        assert r.status_code == 403, r.text

    def test_normal_forbidden(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10"}, cookies=NORMAL)
        assert r.status_code == 403, r.text

    def test_csv_vip_forbidden(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report.csv",
                         params={"date": "2026-09-10"}, cookies=VIP)
        assert r.status_code == 403


# ──────────────────── Validation ────────────────────
class TestValidation:
    def test_invalid_date(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-13-40"}, cookies=ADMIN)
        assert r.status_code == 400

    def test_invalid_start(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10", "start": "bad"},
                         cookies=ADMIN)
        assert r.status_code == 400

    def test_start_after_date(self):
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10",
                                 "start": "2026-09-20"}, cookies=ADMIN)
        assert r.status_code == 400


# ──────────────────── Report shape & ordering ────────────────────
class TestReportShape:
    def test_report_shape_and_order(self, two_products):
        pid1, pid2 = two_products
        r = requests.get(f"{API}/admin/inventory/cutoff-report",
                         params={"date": "2026-09-10"}, cookies=ADMIN)
        assert r.status_code == 200
        data = r.json()
        assert data["cutoff"] == "2026-09-10"
        assert data["currency"] == "CUP"
        assert "totals" in data
        for k in ("num_products", "units", "value", "diff_value",
                  "partial_count"):
            assert k in data["totals"]
        # Rows for both products present with expected fields
        rows_by_id = {p["product_id"]: p for p in data["products"]}
        assert pid1 in rows_by_id and pid2 in rows_by_id
        r1 = rows_by_id[pid1]
        for k in ("opening", "entradas", "ventas", "merma", "consumo",
                  "otra_salida", "ajuste_neto", "final_stock", "wac",
                  "price", "value", "currency", "coverage"):
            assert k in r1
        assert r1["final_stock"] == 10
        assert r1["wac"] == 100.0
        assert r1["value"] == 1000.0
        assert r1["currency"] == "CUP"
        assert r1["coverage"] == "completa"
        # Ordering by value DESC — high must come before low in slice.
        values = [p["value"] for p in data["products"]]
        assert values == sorted(values, reverse=True)


# ──────────────────── CSV ────────────────────
class TestCsv:
    def test_csv_headers_and_totals(self, two_products):
        r = requests.get(f"{API}/admin/inventory/cutoff-report.csv",
                         params={"date": "2026-09-10"}, cookies=ADMIN)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("Content-Type", "")
        text = r.content.decode("utf-8-sig")
        reader = list(csv.reader(io.StringIO(text)))
        header = reader[0]
        for expected in ("Producto", "Existencia inicial", "Entradas",
                         "Ventas", "Merma", "Consumo", "Otras salidas",
                         "Ajuste neto", "Existencia final", "Cobertura"):
            assert expected in header, f"Missing header: {expected}"
        # Costo WAC and Valor headers include currency suffix.
        assert any("Costo WAC" in h for h in header)
        assert any("Valor" in h for h in header)
        # TOTALES row at end
        assert any(row and row[0] == "TOTALES" for row in reader)


# ──────────────────── Counts persist reference_cost ────────────────────
class TestCountFields:
    def test_count_persists_reference_cost(self):
        pid = f"TEST_IPV329C_{uuid.uuid4().hex[:8]}"
        _db.products.insert_one({
            "id": pid, "name": "TEST_CountRef", "category": "Prueba",
            "is_active": True, "stock": 10, "cost_usd": 7.5,
            "price_usd": 15.0, "owner_id": ""})
        try:
            r = requests.post(f"{API}/admin/inventory/counts",
                              json={"product_id": pid, "counted_qty": 8,
                                    "note": "TEST"}, cookies=ADMIN)
            assert r.status_code == 200, r.text
            doc = r.json()
            assert "reference_cost" in doc
            assert doc.get("currency") == "CUP"
            assert "difference_value" in doc
            assert "unit" in doc
            # difference_value = (counted - theoretical) * reference_cost
            diff = doc.get("difference")
            ref = float(doc.get("reference_cost") or 0)
            exp = round(diff * ref, 2)
            assert abs(float(doc["difference_value"]) - exp) < 0.01
        finally:
            _db.inventory_counts.delete_many({"product_id": pid})
            _db.products.delete_one({"id": pid})
