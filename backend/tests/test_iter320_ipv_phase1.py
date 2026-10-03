"""IPV Fase 1 (iter320) — Conteo físico, ajuste autorizado, salidas no-venta
y cierre formal del día. Reglas aprobadas por el operador:
- El conteo NO altera stock; solo un ADMIN con documento puede autorizar ajuste.
- Merma/consumo/otra_salida descuentan stock pero NO son ingreso ni tocan el
  fondo de la empresa.
- Cierre formal deja constancia pero no bloquea nuevos movimientos.
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN, today_havana

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _auth(tok):
    return {"Cookie": f"session_token={tok}"}


@pytest.fixture
def company_product():
    """Produce an isolated company (no owner_id) product."""
    db = _db()
    pid = f"prod_test_ipv_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": pid,
        "name": f"TEST_IPV_{pid[-6:]}",
        "category": "test",
        "price_usd": 10.0,
        "cost_usd": 4.0,
        "stock": 20,
        "is_active": True,
    }
    db.products.insert_one(dict(doc))
    yield doc
    db.products.delete_one({"id": pid})
    db.inventory_counts.delete_many({"product_id": pid})
    db.inventory_movements.delete_many({"product_id": pid})


@pytest.fixture
def vip_product():
    db = _db()
    pid = f"prod_test_vip_{uuid.uuid4().hex[:8]}"
    doc = {"id": pid, "name": "TEST_VIP_prod", "owner_id": "user_test_vip01",
           "price_usd": 5.0, "cost_usd": 2.0, "stock": 10, "is_active": True}
    db.products.insert_one(dict(doc))
    yield doc
    db.products.delete_one({"id": pid})


# ─────────────────── Conteo físico (NO altera stock) ───────────────────
class TestPhysicalCount:
    def test_count_does_not_change_stock(self, company_product):
        pid = company_product["id"]
        r = requests.post(f"{API}/admin/inventory/counts",
                          json={"product_id": pid, "counted_qty": 18, "note": "n"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["counted_qty"] == 18
        assert d["theoretical_stock"] == 20
        assert d["difference"] == -2
        assert d["status"] == "faltante"
        assert d["authorized"] is False
        count_id = d["id"]

        # Stock no cambia
        ctrl = requests.get(f"{API}/admin/inventory/control",
                            headers=_auth(ADMIN_TOKEN)).json()
        row = next(r for r in ctrl if r["product_id"] == pid)
        assert row["stock"] == 20, "El conteo NO debe mover el stock"
        assert row["counted_qty"] == 18
        assert row["count_difference"] == -2
        assert row["count_status"] == "faltante"
        assert row["count_id"] == count_id
        assert row["count_authorized"] is False

    def test_count_sobrante_and_cuadra(self, company_product):
        pid = company_product["id"]
        r = requests.post(f"{API}/admin/inventory/counts",
                          json={"product_id": pid, "counted_qty": 25, "note": ""},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.json()["status"] == "sobrante"
        assert r.json()["difference"] == 5

        r = requests.post(f"{API}/admin/inventory/counts",
                          json={"product_id": pid, "counted_qty": 20, "note": ""},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.json()["status"] == "cuadra"
        assert r.json()["difference"] == 0

    def test_delete_count(self, company_product):
        pid = company_product["id"]
        requests.post(f"{API}/admin/inventory/counts",
                      json={"product_id": pid, "counted_qty": 15},
                      headers=_auth(ADMIN_TOKEN))
        r = requests.delete(f"{API}/admin/inventory/counts/{pid}",
                            headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        ctrl = requests.get(f"{API}/admin/inventory/control",
                            headers=_auth(ADMIN_TOKEN)).json()
        row = next(r for r in ctrl if r["product_id"] == pid)
        assert row["counted_qty"] is None
        assert row["count_status"] == "sin_conteo"

    def test_count_rejects_vip_product(self, vip_product):
        r = requests.post(f"{API}/admin/inventory/counts",
                          json={"product_id": vip_product["id"],
                                "counted_qty": 1},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 400


# ─────────────────── Ajuste autorizado (SOLO admin, con doc) ───────────────────
class TestCountAdjustment:
    def _make_count(self, pid, qty=18):
        r = requests.post(f"{API}/admin/inventory/counts",
                          json={"product_id": pid, "counted_qty": qty},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        return r.json()

    def test_adjust_applies_delta_and_is_idempotent(self, company_product):
        pid = company_product["id"]
        c = self._make_count(pid, 18)  # dif = -2 → ajuste_neg
        cid = c["id"]
        r = requests.post(f"{API}/admin/inventory/counts/{cid}/adjust",
                          json={"document": "FACT-001", "note": "n"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["authorized"] is True
        assert d["status"] == "ajustado"
        assert d["adjustment_movement_id"]
        # Stock baja a 18
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 18

        # Movimiento ajuste_neg existe
        mov = _db().inventory_movements.find_one(
            {"id": d["adjustment_movement_id"]}, {"_id": 0})
        assert mov["type"] == "ajuste_neg"
        assert mov["quantity"] == 2

        # Idempotente — un segundo adjust → 409
        r2 = requests.post(f"{API}/admin/inventory/counts/{cid}/adjust",
                           json={"document": "FACT-002"},
                           headers=_auth(ADMIN_TOKEN))
        assert r2.status_code == 409

        # Recontar mismo día → 409
        r3 = requests.post(f"{API}/admin/inventory/counts",
                           json={"product_id": pid, "counted_qty": 10},
                           headers=_auth(ADMIN_TOKEN))
        assert r3.status_code == 409

        # Borrar conteo autorizado → 409
        r4 = requests.delete(f"{API}/admin/inventory/counts/{pid}",
                             headers=_auth(ADMIN_TOKEN))
        assert r4.status_code == 409

    def test_adjust_sobrante_increases_stock(self, company_product):
        pid = company_product["id"]
        c = self._make_count(pid, 25)  # dif = +5 → ajuste_pos
        r = requests.post(f"{API}/admin/inventory/counts/{c['id']}/adjust",
                          json={"document": "DOC-1"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 25

    def test_adjust_requires_document(self, company_product):
        c = self._make_count(company_product["id"], 15)
        # Documento vacío → 422 (Pydantic min_length=2) o 400
        r = requests.post(f"{API}/admin/inventory/counts/{c['id']}/adjust",
                          json={"document": ""},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code in (400, 422)
        # <2 chars → 422
        r2 = requests.post(f"{API}/admin/inventory/counts/{c['id']}/adjust",
                           json={"document": "x"},
                           headers=_auth(ADMIN_TOKEN))
        assert r2.status_code in (400, 422)

    def test_adjust_zero_difference_400(self, company_product):
        c = self._make_count(company_product["id"], 20)  # dif=0
        r = requests.post(f"{API}/admin/inventory/counts/{c['id']}/adjust",
                          json={"document": "DOC-X"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 400


# ─────────────────── Permisos ───────────────────
class TestPermissions:
    def test_employee_can_count_but_not_adjust_nor_close(self, company_product):
        pid = company_product["id"]
        r = requests.post(f"{API}/admin/inventory/counts",
                          json={"product_id": pid, "counted_qty": 18},
                          headers=_auth(EMPLOYEE_TOKEN))
        assert r.status_code == 200, f"Employee should count: {r.status_code} {r.text}"
        cid = r.json()["id"]
        # Adjust prohibido
        r2 = requests.post(f"{API}/admin/inventory/counts/{cid}/adjust",
                           json={"document": "FACT-001"},
                           headers=_auth(EMPLOYEE_TOKEN))
        assert r2.status_code == 403
        # Cierre prohibido
        r3 = requests.post(f"{API}/admin/inventory/close-review",
                           json={"date": today_havana(), "responsable": "e"},
                           headers=_auth(EMPLOYEE_TOKEN))
        assert r3.status_code == 403

    def test_normal_and_vip_forbidden(self, company_product):
        for tok in (NORMAL_TOKEN, VIP_TOKEN):
            r = requests.post(f"{API}/admin/inventory/counts",
                              json={"product_id": company_product["id"],
                                    "counted_qty": 1},
                              headers=_auth(tok))
            assert r.status_code == 403, f"{tok}: {r.status_code}"
            r2 = requests.get(f"{API}/admin/inventory/control",
                              headers=_auth(tok))
            assert r2.status_code == 403
            r3 = requests.get(f"{API}/admin/inventory/close-review",
                              headers=_auth(tok))
            assert r3.status_code == 403


# ─────────────────── Salidas no-venta ───────────────────
class TestNonSaleOutputs:
    @pytest.mark.parametrize("mtype", ["merma", "consumo", "otra_salida"])
    def test_output_decreases_stock_without_revenue(self, company_product, mtype):
        pid = company_product["id"]
        day = today_havana()
        # fondo antes
        fund_before = _db().company_fund_adjustments.count_documents({})

        r = requests.post(f"{API}/admin/inventory/movements",
                          json={"product_id": pid, "type": mtype,
                                "quantity": 3, "note": "doc-ok"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        mov = r.json()
        assert mov["type"] == mtype
        assert mov["quantity"] == 3
        assert mov["profit"] == 0
        # Stock -3
        p = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert p["stock"] == 17

        # No tocó fondo
        fund_after = _db().company_fund_adjustments.count_documents({})
        assert fund_after == fund_before, "Salida no-venta no debe crear fondo"

        # daily-close no incluye estas unidades en ventas
        dc = requests.get(f"{API}/admin/inventory/daily-close",
                          params={"date": day},
                          headers=_auth(ADMIN_TOKEN)).json()
        assert dc["fisica"]["ventas"] == 0
        assert dc["fisica"]["caja_neta"] == 0
        assert dc["fisica"]["ganancia"] == 0
        assert dc["salidas"][mtype]["unidades"] >= 3
        # El movimiento aparece en GET movements
        lst = requests.get(f"{API}/admin/inventory/movements",
                           params={"product_id": pid, "type": mtype},
                           headers=_auth(ADMIN_TOKEN)).json()
        assert any(m["id"] == mov["id"] for m in lst)


# ─────────────────── Revisión del cierre ───────────────────
class TestCloseReview:
    def test_close_review_descuadra_with_diff_and_salida_sin_doc(self, company_product):
        pid = company_product["id"]
        day = today_havana()
        # Diferencia sin ajustar
        requests.post(f"{API}/admin/inventory/counts",
                      json={"product_id": pid, "counted_qty": 15},
                      headers=_auth(ADMIN_TOKEN))
        # Salida sin documento (nota vacía)
        requests.post(f"{API}/admin/inventory/movements",
                      json={"product_id": pid, "type": "merma",
                            "quantity": 1, "note": ""},
                      headers=_auth(ADMIN_TOKEN))

        r = requests.get(f"{API}/admin/inventory/close-review",
                         params={"date": day},
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        rv = r.json()
        assert rv["resultado_sugerido"] == "descuadra"
        assert rv["alerts"]["diferencias"] >= 1
        assert rv["alerts"]["salidas_sin_documento"] >= 1
        assert rv["salidas"]["merma"]["unidades"] >= 1

    def test_close_review_invalid_date(self):
        r = requests.get(f"{API}/admin/inventory/close-review",
                         params={"date": "no-fecha"},
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 400

    def test_close_review_save_admin_only_persists(self, company_product):
        day = today_havana()
        r = requests.post(f"{API}/admin/inventory/close-review",
                          json={"date": day, "responsable": "Juan",
                                "revisado_por": "Ana", "folio": "F-001",
                                "note": "ok"},
                          headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        rv2 = requests.get(f"{API}/admin/inventory/close-review",
                           params={"date": day},
                           headers=_auth(ADMIN_TOKEN)).json()
        close = rv2["close"]
        assert close is not None
        assert close["responsable"] == "Juan"
        assert close["revisado_por"] == "Ana"
        assert close["folio"] == "F-001"
        assert close["closed_by_email"]

        # No bloquea nuevos movimientos tras cerrar
        pid = company_product["id"]
        r3 = requests.post(f"{API}/admin/inventory/movements",
                           json={"product_id": pid, "type": "entrada",
                                 "quantity": 1, "unit_cost": 4.0,
                                 "note": "post-cierre"},
                           headers=_auth(ADMIN_TOKEN))
        assert r3.status_code == 200
