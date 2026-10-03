"""IPV Fase 2 (iter321) — WAC + lotes + valoración FIFO + acta PDF.

Reglas aprobadas:
- Entrada calcula WAC = (base·old + qty·entry) / (base+qty).
- Cada entrada crea 1 lote (idempotente por movement_id).
- Valoración FIFO en lectura: existencia restante = lotes más recientes.
- Acta de conteo PDF firmable por fecha.
- Permisos 'products' en valuation/CSV/count-sheet.
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


def _delete_product(pid):
    db = _db()
    db.products.delete_one({"id": pid})
    db.inventory_movements.delete_many({"product_id": pid})
    db.inventory_lots.delete_many({"product_id": pid})
    db.inventory_counts.delete_many({"product_id": pid})


@pytest.fixture
def company_product_api():
    """Crea un producto de empresa vía POST /api/admin/products
    (dispara el lote 'alta' inicial)."""
    name = f"TEST_WAC_{uuid.uuid4().hex[:8]}"
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
    _delete_product(p["id"])


@pytest.fixture
def vip_product():
    db = _db()
    pid = f"prod_test_vip_{uuid.uuid4().hex[:8]}"
    doc = {"id": pid, "name": f"TEST_VIP_{pid[-6:]}",
           "owner_id": "user_test_vip01",
           "price_usd": 5.0, "cost_usd": 2.0, "stock": 10, "is_active": True}
    db.products.insert_one(dict(doc))
    yield doc
    _delete_product(pid)


# ────────────────── WAC en entrada ──────────────────
class TestWACOnEntry:
    def test_wac_computed_on_entry_and_two_lots_created(self, company_product_api):
        pid = company_product_api["id"]
        # Entrada: 10@200 → WAC = (10*100 + 10*200)/20 = 150
        r = requests.post(f"{API}/admin/inventory/movements",
                          json={"product_id": pid, "type": "entrada",
                                "quantity": 10, "unit_cost": 200.0},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text

        # cost_usd en producto = 150 (no 200)
        prod = _db().products.find_one({"id": pid}, {"_id": 0})
        assert prod["stock"] == 20
        assert abs(float(prod["cost_usd"]) - 150.0) < 0.01, \
            f"WAC esperado 150, actual {prod['cost_usd']}"

        # Reflejado en /control
        ctrl = requests.get(f"{API}/admin/inventory/control",
                            headers=_auth(ADMIN_TOKEN)).json()
        row = next(x for x in ctrl if x["product_id"] == pid)
        assert abs(float(row["cost_usd"]) - 150.0) < 0.01

        # 2 lotes
        lots = list(_db().inventory_lots.find({"product_id": pid}))
        assert len(lots) == 2, f"Esperados 2 lotes, hay {len(lots)}"
        costs = sorted([float(l["unit_cost"]) for l in lots])
        assert costs == [100.0, 200.0]
        qtys = sorted([int(l["qty"]) for l in lots])
        assert qtys == [10, 10]


# ────────────────── WAC en profit de venta ──────────────────
class TestWACOnSaleProfit:
    def test_sale_uses_wac_for_cost_of_sale_and_profit(self, company_product_api):
        pid = company_product_api["id"]
        requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "entrada",
                            "quantity": 10, "unit_cost": 200.0},
                      headers=_auth(ADMIN_TOKEN))
        price = float(company_product_api.get("price_usd") or 300.0)
        # Venta 5
        r = requests.post(f"{API}/admin/inventory/movements",
                          json={"product_id": pid, "type": "venta",
                                "quantity": 5},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        mov = r.json()
        # cost_of_sale = 150*5 = 750, profit = price*5 - 750
        assert abs(float(mov.get("cost_of_sale", 0)) - 750.0) < 0.5, \
            f"cost_of_sale esperado 750, actual {mov.get('cost_of_sale')}"
        expected_profit = price * 5 - 750.0
        assert abs(float(mov.get("profit", 0)) - expected_profit) < 0.5, \
            f"profit esperado {expected_profit}, actual {mov.get('profit')}"


# ────────────────── Lote idempotente ──────────────────
class TestLotIdempotent:
    def test_each_entry_creates_exactly_one_lot(self, company_product_api):
        pid = company_product_api["id"]
        # 3 entradas
        for q, c in [(5, 150.0), (2, 200.0), (3, 180.0)]:
            r = requests.post(f"{API}/admin/inventory/movements",
                              json={"product_id": pid, "type": "entrada",
                                    "quantity": q, "unit_cost": c},
                              headers=_auth(ADMIN_TOKEN))
            assert r.status_code == 200
        lots = list(_db().inventory_lots.find({"product_id": pid}))
        # 1 alta + 3 entradas = 4 lotes
        assert len(lots) == 4
        # movement_ids únicos
        mids = [l.get("movement_id") for l in lots]
        assert len(set(mids)) == len(mids)


# ────────────────── Valoración FIFO ──────────────────
class TestValuationFIFO:
    def test_valuation_shape_and_fifo_depletion(self, company_product_api):
        pid = company_product_api["id"]
        # Entrada 10@200 → 2 lotes
        requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "entrada",
                            "quantity": 10, "unit_cost": 200.0},
                      headers=_auth(ADMIN_TOKEN))

        r = requests.get(f"{API}/admin/inventory/valuation",
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "products" in data and "totals" in data
        for key in ("units", "value_wac", "value_lots",
                    "num_products", "stock_sin_lote"):
            assert key in data["totals"], f"Falta totals.{key}"

        prod = next(p for p in data["products"] if p["product_id"] == pid)
        for key in ("stock", "wac", "inventory_value_wac",
                    "inventory_value_lots", "stock_sin_lote",
                    "num_lotes", "lots"):
            assert key in prod, f"Falta producto.{key}"
        assert prod["stock"] == 20
        assert abs(prod["wac"] - 150.0) < 0.01
        assert prod["stock_sin_lote"] == 0
        assert prod["num_lotes"] == 2
        # Sin ventas: ambos lotes al tope
        assert prod["inventory_value_lots"] == 3000.0
        rem_by_cost = {l["unit_cost"]: l["remaining"] for l in prod["lots"]}
        assert rem_by_cost[100.0] == 10
        assert rem_by_cost[200.0] == 10

        # Venta 5 → stock=15. FIFO: consume primero el lote MÁS ANTIGUO.
        requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "venta",
                            "quantity": 5},
                      headers=_auth(ADMIN_TOKEN))
        r2 = requests.get(f"{API}/admin/inventory/valuation",
                          headers=_auth(ADMIN_TOKEN))
        prod2 = next(p for p in r2.json()["products"] if p["product_id"] == pid)
        assert prod2["stock"] == 15
        rem2 = {l["unit_cost"]: l["remaining"] for l in prod2["lots"]}
        # Lote viejo (100) se consume primero: queda 5. Nuevo (200): queda 10.
        assert rem2[200.0] == 10, f"Lote nuevo debe seguir 10, actual {rem2[200.0]}"
        assert rem2[100.0] == 5, f"Lote viejo debe quedar 5 (FIFO), actual {rem2[100.0]}"
        assert prod2["inventory_value_lots"] == 2500.0


# ────────────────── CSV ──────────────────
class TestValuationCSV:
    def test_csv_response(self, company_product_api):
        pid = company_product_api["id"]
        requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "entrada",
                            "quantity": 5, "unit_cost": 180.0},
                      headers=_auth(ADMIN_TOKEN))
        r = requests.get(f"{API}/admin/inventory/valuation.csv",
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/csv")
        text = r.content.decode("utf-8-sig")
        rows = list(csv.reader(text.splitlines()))
        assert len(rows) >= 2  # header + al menos una fila
        header = rows[0]
        assert "Producto" in header[0]


# ────────────────── Acta PDF ──────────────────
class TestCountSheetPDF:
    def test_pdf_ok_without_close(self):
        from conftest import today_havana
        day = today_havana()
        r = requests.get(f"{API}/admin/inventory/count-sheet.pdf",
                         params={"date": day},
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_pdf_invalid_date_400(self):
        r = requests.get(f"{API}/admin/inventory/count-sheet.pdf",
                         params={"date": "2026-13-40"},
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 400

    def test_pdf_with_close_still_200(self):
        from conftest import today_havana
        day = today_havana()
        # Guardar un cierre con responsable/revisor/folio
        rc = requests.post(f"{API}/admin/inventory/close-review",
                           json={"date": day, "responsable": "Resp321",
                                 "revisado_por": "Rev321",
                                 "folio": "F-321", "note": "iter321"},
                           headers=_auth(ADMIN_TOKEN))
        assert rc.status_code == 200, rc.text
        r = requests.get(f"{API}/admin/inventory/count-sheet.pdf",
                         params={"date": day},
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"


# ────────────────── Permisos ──────────────────
class TestPermissions:
    def test_employee_allowed(self):
        from conftest import today_havana
        for path, params in [
            ("/admin/inventory/valuation", None),
            ("/admin/inventory/valuation.csv", None),
            ("/admin/inventory/count-sheet.pdf", {"date": today_havana()}),
        ]:
            r = requests.get(f"{API}{path}", params=params,
                             headers=_auth(EMPLOYEE_TOKEN))
            assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:100]}"

    def test_vip_and_normal_forbidden(self):
        from conftest import today_havana
        for tok in (VIP_TOKEN, NORMAL_TOKEN):
            for path, params in [
                ("/admin/inventory/valuation", None),
                ("/admin/inventory/valuation.csv", None),
                ("/admin/inventory/count-sheet.pdf", {"date": today_havana()}),
            ]:
                r = requests.get(f"{API}{path}", params=params,
                                 headers=_auth(tok))
                assert r.status_code == 403, f"{tok} {path} → {r.status_code}"


# ────────────────── Stock sin lote (legacy pre-Fase 2) ──────────────────
class TestStockSinLote:
    def test_legacy_product_without_lots(self):
        db = _db()
        pid = f"prod_test_legacy_{uuid.uuid4().hex[:8]}"
        db.products.insert_one({
            "id": pid, "name": f"TEST_LEGACY_{pid[-6:]}", "category": "test",
            "price_usd": 50.0, "cost_usd": 10.0, "stock": 7, "is_active": True,
        })
        # Ningún lote asociado
        try:
            r = requests.get(f"{API}/admin/inventory/valuation",
                             headers=_auth(ADMIN_TOKEN))
            assert r.status_code == 200
            data = r.json()
            p = next((x for x in data["products"] if x["product_id"] == pid),
                     None)
            assert p is not None
            assert p["stock_sin_lote"] == 7
            assert p["num_lotes"] == 0
            assert p["inventory_value_lots"] == 0
            # WAC retiene el valor
            assert abs(p["inventory_value_wac"] - 70.0) < 0.01
            assert data["totals"]["stock_sin_lote"] >= 7
        finally:
            _delete_product(pid)


# ────────────────── VIP product rechaza entrada ──────────────────
class TestVIPProductRejected:
    def test_entrada_on_vip_product_400(self, vip_product):
        r = requests.post(f"{API}/admin/inventory/movements",
                          json={"product_id": vip_product["id"],
                                "type": "entrada", "quantity": 1,
                                "unit_cost": 5.0},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 400
