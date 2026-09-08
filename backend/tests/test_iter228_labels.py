"""iter228 — Etiquetas imprimibles con código de barras.

Cubre:
- POST /admin/inventory/barcode/generate crea EAN-13 internos (prefijo 200,
  dígito de control válido, únicos) solo para productos sin código.
- Producto que ya tiene código → generated=False y conserva el suyo.
- Productos VIP se omiten silenciosamente.
- GET /admin/inventory/labels.pdf devuelve un PDF válido (%PDF), respeta
  `copies` y excluye productos sin código (400 si ninguno tiene).
- El código generado funciona con el lookup del escáner (integración iter227).
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER228TEST"


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
        "price_usd": 12.0, "cost_usd": 7.0, "stock": 4,
        "category": "iter228test", "is_active": True,
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


def _ean13_ok(code: str) -> bool:
    if not (code.isdigit() and len(code) == 13):
        return False
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(code[:12]))
    return code[12] == str((10 - s % 10) % 10)


class TestLabels:
    def teardown_method(self, _):
        _cleanup()

    def test_generate_internal_codes_unique_and_valid(self):
        p1 = _create_product()
        p2 = _create_product()
        r = requests.post(f"{API}/admin/inventory/barcode/generate",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_ids": [p1["id"], p2["id"]]})
        assert r.status_code == 200, r.text
        out = r.json()
        assert len(out) == 2
        codes = {o["barcode"] for o in out}
        assert len(codes) == 2
        for o in out:
            assert o["generated"] is True
            assert o["barcode"].startswith("200")
            assert _ean13_ok(o["barcode"])

    def test_existing_code_preserved(self):
        p = _create_product()
        code = f"779{int(time.time() * 1000) % 10**10:010d}"
        requests.post(f"{API}/admin/inventory/barcode/assign",
                      headers=_h(ADMIN_TOKEN),
                      json={"product_id": p["id"], "barcode": code})
        r = requests.post(f"{API}/admin/inventory/barcode/generate",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_ids": [p["id"]]})
        assert r.status_code == 200
        assert r.json()[0] == {"product_id": p["id"], "barcode": code,
                               "generated": False}

    def test_vip_products_skipped(self):
        db = _db()
        pid = f"prod_{MARK}_vip"
        db.products.insert_one({
            "id": pid, "name": f"{MARK}_VipProd", "price_usd": 5.0,
            "stock": 3, "owner_id": "user_test_vip01", "is_active": True,
        })
        r = requests.post(f"{API}/admin/inventory/barcode/generate",
                          headers=_h(ADMIN_TOKEN),
                          json={"product_ids": [pid]})
        assert r.status_code == 200
        assert r.json() == []
        assert not db.products.find_one({"id": pid}).get("barcode")

    def test_labels_pdf_valid_and_copies(self):
        p = _create_product()
        requests.post(f"{API}/admin/inventory/barcode/generate",
                      headers=_h(ADMIN_TOKEN), json={"product_ids": [p["id"]]})
        r = requests.get(f"{API}/admin/inventory/labels.pdf",
                         headers=_h(ADMIN_TOKEN),
                         params={"product_ids": p["id"], "copies": 3})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 800

    def test_labels_pdf_400_when_no_codes(self):
        p = _create_product()  # sin código
        r = requests.get(f"{API}/admin/inventory/labels.pdf",
                         headers=_h(ADMIN_TOKEN),
                         params={"product_ids": p["id"]})
        assert r.status_code == 400

    def test_generated_code_works_with_scanner_lookup(self):
        p = _create_product()
        code = requests.post(f"{API}/admin/inventory/barcode/generate",
                             headers=_h(ADMIN_TOKEN),
                             json={"product_ids": [p["id"]]}).json()[0]["barcode"]
        r = requests.get(f"{API}/admin/inventory/barcode/{code}",
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.json()["product_id"] == p["id"]

    def test_normal_client_forbidden(self):
        p = _create_product()
        r = requests.post(f"{API}/admin/inventory/barcode/generate",
                          headers=_h(NORMAL_TOKEN),
                          json={"product_ids": [p["id"]]})
        assert r.status_code == 403
        r2 = requests.get(f"{API}/admin/inventory/labels.pdf",
                          headers=_h(NORMAL_TOKEN),
                          params={"product_ids": p["id"]})
        assert r2.status_code == 403
