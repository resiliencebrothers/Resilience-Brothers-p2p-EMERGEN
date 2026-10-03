"""iter322 — Valoración IPV Fase 2: margen por lote + rotación/capital.

- MARGEN POR LOTE: por cada lote → margin_unit, margin_pct, remaining_margin.
- MARGEN POR PRODUCTO (WAC): margin_unit_wac, margin_pct_wac, expected_margin.
- FIFO en el margen: la venta consume el lote MÁS ANTIGUO primero (remaining
  del lote viejo baja; remaining_margin = remaining·margin_unit).
- ROTACIÓN del período (window configurable): sold_window, daily_rate,
  sellout_days, rotation, capital_status, immobilized.
- Totales nuevos: expected_margin, immobilized_value, immobilized_count.
- CSV ampliado con las nuevas columnas.
- Permisos: employee (perms vacíos) 200, vip/normal 403.
"""
import os
import csv
import uuid
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _auth(tok):
    return {"Cookie": f"session_token={tok}"}


def _cleanup(pid):
    db = _db()
    db.products.delete_one({"id": pid})
    db.inventory_movements.delete_many({"product_id": pid})
    db.inventory_lots.delete_many({"product_id": pid})


@pytest.fixture
def product():
    """price=300, cost=100, stock=10 → crea 1 lote 'alta'."""
    name = f"TEST_MR_{uuid.uuid4().hex[:8]}"
    payload = {"name": name, "category": "test",
               "price_usd": 300.0, "cost_usd": 100.0, "stock": 10}
    r = requests.post(f"{API}/admin/products", json=payload,
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    p = r.json()
    yield p
    try:
        requests.delete(f"{API}/admin/products/{p['id']}",
                        headers=_auth(ADMIN_TOKEN))
    except Exception:
        pass
    _cleanup(p["id"])


def _entrada(pid, qty, cost):
    r = requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "entrada",
                            "quantity": qty, "unit_cost": cost},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text


def _venta(pid, qty):
    r = requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "venta",
                            "quantity": qty},
                      headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _get_val(window=30, tok=ADMIN_TOKEN):
    r = requests.get(f"{API}/admin/inventory/valuation",
                     params={"window": window}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    return r.json()


def _find(data, pid):
    return next((p for p in data["products"] if p["product_id"] == pid), None)


# ────────────────── Margen por lote (sin ventas) ──────────────────
class TestLotMargin:
    def test_lot_margin_unit_pct_remaining(self, product):
        pid = product["id"]
        _entrada(pid, 10, 200.0)  # lote B
        data = _get_val()
        p = _find(data, pid)
        assert p is not None
        assert p["stock"] == 20
        # Producto a nivel WAC
        assert abs(p["wac"] - 150.0) < 0.01
        assert abs(p["margin_unit_wac"] - 150.0) < 0.01
        assert abs(p["margin_pct_wac"] - 50.0) < 0.1
        assert abs(p["expected_margin"] - 3000.0) < 0.5

        lots_by_cost = {l["unit_cost"]: l for l in p["lots"]}
        A = lots_by_cost[100.0]
        B = lots_by_cost[200.0]
        # Lote A (viejo)
        assert abs(A["margin_unit"] - 200.0) < 0.01
        assert abs(A["margin_pct"] - 66.67) < 0.1
        assert A["remaining"] == 10
        assert abs(A["remaining_margin"] - 2000.0) < 0.5
        # Lote B (nuevo)
        assert abs(B["margin_unit"] - 100.0) < 0.01
        assert abs(B["margin_pct"] - 33.33) < 0.1
        assert B["remaining"] == 10
        assert abs(B["remaining_margin"] - 1000.0) < 0.5


# ────────────────── FIFO depletes oldest first (margen restante) ──────────────────
class TestFIFOMarginDepletion:
    def test_sale_consumes_oldest_lot_first(self, product):
        pid = product["id"]
        _entrada(pid, 10, 200.0)
        _venta(pid, 5)
        data = _get_val()
        p = _find(data, pid)
        assert p["stock"] == 15
        lots_by_cost = {l["unit_cost"]: l for l in p["lots"]}
        A = lots_by_cost[100.0]  # viejo
        B = lots_by_cost[200.0]  # nuevo
        assert A["remaining"] == 5, f"Lote viejo esperado 5, actual {A['remaining']}"
        assert B["remaining"] == 10
        # remaining_margin = remaining · margin_unit
        assert abs(A["remaining_margin"] - 5 * 200.0) < 0.5
        assert abs(B["remaining_margin"] - 10 * 100.0) < 0.5


# ────────────────── Rotación y capital_status ──────────────────
class TestRotationAndCapital:
    def test_recent_sale_is_not_sin_ventas(self, product):
        pid = product["id"]
        _entrada(pid, 10, 200.0)
        _venta(pid, 5)
        data = _get_val(window=30)
        assert data.get("window_days") == 30
        p = _find(data, pid)
        for k in ("sold_window", "daily_rate", "sellout_days",
                  "rotation", "capital_status", "immobilized"):
            assert k in p, f"Falta {k}"
        assert p["sold_window"] >= 5
        assert p["capital_status"] != "sin_ventas"
        # Totales nuevos
        for k in ("expected_margin", "immobilized_value", "immobilized_count"):
            assert k in data["totals"], f"Falta totals.{k}"

    def test_no_sales_product_is_immobilized(self):
        """Producto nuevo con stock > 0 y SIN ventas → sin_ventas + immobilized."""
        name = f"TEST_IMMOB_{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/admin/products",
                          json={"name": name, "category": "test",
                                "price_usd": 50.0, "cost_usd": 20.0,
                                "stock": 5},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        try:
            data = _get_val(window=30)
            p = _find(data, pid)
            assert p is not None
            assert p["sold_window"] == 0
            assert p["capital_status"] == "sin_ventas"
            assert p["immobilized"] is True
            # immobilized_value incluye este producto (20·5 = 100)
            assert data["totals"]["immobilized_value"] >= 100.0 - 0.5
            assert data["totals"]["immobilized_count"] >= 1
        finally:
            requests.delete(f"{API}/admin/products/{pid}",
                            headers=_auth(ADMIN_TOKEN))
            _cleanup(pid)


# ────────────────── Window configurable ──────────────────
class TestWindowParam:
    def test_window_default_30(self):
        r = requests.get(f"{API}/admin/inventory/valuation",
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.json().get("window_days") == 30

    def test_window_param_echoed(self):
        for w in (1, 60, 90):
            data = _get_val(window=w)
            assert data["window_days"] == w

    def test_window_1_vs_90_changes_sold_window(self, product):
        pid = product["id"]
        _entrada(pid, 10, 200.0)
        _venta(pid, 5)
        d1 = _find(_get_val(window=1), pid)
        d90 = _find(_get_val(window=90), pid)
        # Venta hoy entra tanto en 1 como en 90 → sold_window >= 5 en ambas.
        # Para un producto cuya venta cae HOY, ambas deben verla; pero el
        # período 90 nunca puede ser menor que el de 1 día.
        assert d90["sold_window"] >= d1["sold_window"]


# ────────────────── CSV ampliado ──────────────────
class TestCSVExtended:
    def test_csv_has_new_columns(self, product):
        pid = product["id"]
        _entrada(pid, 10, 200.0)
        r = requests.get(f"{API}/admin/inventory/valuation.csv",
                         params={"window": 30}, headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/csv")
        text = r.content.decode("utf-8-sig")
        rows = list(csv.reader(text.splitlines()))
        assert len(rows) >= 2
        header = rows[0]
        for col in ("Precio venta", "Margen %", "Margen esperado",
                    "Vendidas (período)", "Días p/agotar", "Estado capital",
                    "Lote margen %", "Lote margen restante"):
            assert col in header, f"Falta columna CSV: {col} (header={header})"


# ────────────────── Permisos ──────────────────
class TestPermissions:
    def test_employee_200(self):
        for path in ("/admin/inventory/valuation",
                     "/admin/inventory/valuation.csv"):
            r = requests.get(f"{API}{path}", headers=_auth(EMPLOYEE_TOKEN))
            assert r.status_code == 200, f"{path} → {r.status_code}"

    def test_vip_normal_403(self):
        for tok in (VIP_TOKEN, NORMAL_TOKEN):
            for path in ("/admin/inventory/valuation",
                         "/admin/inventory/valuation.csv"):
                r = requests.get(f"{API}{path}", headers=_auth(tok))
                assert r.status_code == 403, \
                    f"{tok} {path} → {r.status_code}"
