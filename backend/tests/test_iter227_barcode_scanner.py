"""iter227 — Escáner de código de barras (inventario tienda física).

Cubre:
- Vincular un código a un producto de la empresa (assign) + auditoría.
- Lookup por código: 200 con ficha / 404 si no vinculado.
- Código duplicado en otro producto → 409 con el nombre del otro.
- Re-vincular el mismo producto (actualizar su código) → 200.
- Producto de vendedor VIP → 400.
- Flujo completo: escanear → venta/entrada por movements descuenta/suma stock.
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER227TEST"


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _create_product(**overrides):
    payload = {
        "name": f"{MARK}_Prod_{int(time.time() * 1000)}",
        "price_usd": 8.0, "cost_usd": 5.0, "stock": 10,
        "category": "iter227test", "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup():
    db = _db()
    ids = [p["id"] for p in db.products.find({"name": {"$regex": f"^{MARK}"}})]
    db.products.delete_many({"id": {"$in": ids}})
    db.inventory_movements.delete_many({"product_id": {"$in": ids}})


def _code():
    return f"779{int(time.time() * 1000) % 10**10:010d}"


class TestBarcode:
    def teardown_method(self, _):
        _cleanup()

    def test_assign_and_lookup(self):
        p = _create_product()
        code = _code()
        r = requests.post(f"{API}/admin/inventory/barcode/assign",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_id": p["id"], "barcode": code})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == p["name"]

        r2 = requests.get(f"{API}/admin/inventory/barcode/{code}",
                          headers=_h(ADMIN_TOKEN))
        assert r2.status_code == 200, r2.text
        hit = r2.json()
        assert hit["product_id"] == p["id"]
        assert hit["stock"] == 10
        assert hit["price_usd"] == 8.0

    def test_lookup_unknown_404(self):
        r = requests.get(f"{API}/admin/inventory/barcode/0000000000000",
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 404

    def test_duplicate_code_on_other_product_409(self):
        p1 = _create_product()
        p2 = _create_product()
        code = _code()
        r = requests.post(f"{API}/admin/inventory/barcode/assign",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_id": p1["id"], "barcode": code})
        assert r.status_code == 200, r.text
        r2 = requests.post(f"{API}/admin/inventory/barcode/assign",
                           headers=_h(ADMIN_TOKEN),
                           json={"product_id": p2["id"], "barcode": code})
        assert r2.status_code == 409, r2.text
        assert p1["name"] in r2.json()["detail"]

    def test_reassign_same_product_updates_code(self):
        p = _create_product()
        c1, c2 = _code(), _code() + "9"
        for c in (c1, c2):
            r = requests.post(f"{API}/admin/inventory/barcode/assign",
                              headers=_h(ADMIN_TOKEN),
                              json={"product_id": p["id"], "barcode": c})
            assert r.status_code == 200, r.text
        assert requests.get(f"{API}/admin/inventory/barcode/{c2}",
                            headers=_h(ADMIN_TOKEN)).status_code == 200
        assert requests.get(f"{API}/admin/inventory/barcode/{c1}",
                            headers=_h(ADMIN_TOKEN)).status_code == 404

    def test_vip_product_rejected_400(self):
        db = _db()
        pid = f"prod_{MARK}_vip"
        db.products.insert_one({
            "id": pid, "name": f"{MARK}_VipProd", "price_usd": 5.0,
            "stock": 3, "owner_id": "user_test_vip01",
            "is_active": True, "approval_status": "approved",
        })
        r = requests.post(f"{API}/admin/inventory/barcode/assign",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_id": pid, "barcode": _code()})
        assert r.status_code == 400

    def test_normal_client_cannot_use_scanner_endpoints(self):
        p = _create_product()
        code = _code()
        r = requests.post(f"{API}/admin/inventory/barcode/assign",
                          headers=_h(NORMAL_TOKEN),
                          json={"product_id": p["id"], "barcode": code})
        assert r.status_code == 403
        r2 = requests.get(f"{API}/admin/inventory/barcode/{code}",
                          headers=_h(NORMAL_TOKEN))
        assert r2.status_code == 403

    def test_scan_flow_sale_and_entry_move_stock(self):
        p = _create_product(stock=10)
        code = _code()
        requests.post(f"{API}/admin/inventory/barcode/assign",
                      headers=_h(ADMIN_TOKEN),
                      json={"product_id": p["id"], "barcode": code})
        hit = requests.get(f"{API}/admin/inventory/barcode/{code}",
                           headers=_h(ADMIN_TOKEN)).json()

        # venta de 2 con precio del producto
        r = requests.post(f"{API}/admin/inventory/movements",
                          headers=_h(ADMIN_TOKEN), json={
                              "product_id": hit["product_id"], "type": "venta",
                              "quantity": 2, "note": "Registrado con escáner"})
        assert r.status_code == 200, r.text
        assert r.json()["profit"] == 6.0  # (8−5)×2

        # entrada de 5
        r2 = requests.post(f"{API}/admin/inventory/movements",
                           headers=_h(ADMIN_TOKEN), json={
                               "product_id": hit["product_id"], "type": "entrada",
                               "quantity": 5, "note": "Registrado con escáner"})
        assert r2.status_code == 200, r2.text

        db = _db()
        assert db.products.find_one({"id": p["id"]})["stock"] == 13  # 10−2+5
