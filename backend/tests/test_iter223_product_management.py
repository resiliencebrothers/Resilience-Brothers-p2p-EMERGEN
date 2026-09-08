"""iter223 — Gestión de productos del inventario:
- GET /admin/products lista TODOS los productos de la empresa (incl. ocultos,
  excluye los de vendedores VIP).
- POST /admin/products/{id}/toggle-active publica/oculta en el marketplace.
- Migración única: los productos del Excel quedan activos (visibles).
"""
import os
import time

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER223TEST"


def _h(tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _db()
    ids = [p["id"] for p in db.products.find({"category": "iter223test"}, {"id": 1})]
    db.products.delete_many({"category": "iter223test"})
    if ids:
        db.inventory_movements.delete_many({"product_id": {"$in": ids}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _create(**overrides):
    payload = {"name": f"{MARK}_{int(time.time()*1000)}", "description": "",
               "image_url": "", "price_usd": 5.0, "cost_usd": 3.0,
               "stock": 4, "category": "iter223test", "is_active": False}
    payload.update(overrides)
    r = requests.post(f"{API}/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_list_includes_inactive_and_excludes_vendor():
    hidden = _create(is_active=False)
    r = requests.get(f"{API}/admin/products", headers=_h(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    by_id = {p["id"]: p for p in r.json()}
    assert hidden["id"] in by_id
    assert by_id[hidden["id"]]["is_active"] is False
    # ningún producto de vendedor VIP en el listado de empresa
    assert all(not p.get("owner_id") for p in r.json())
    # el endpoint público NO lo muestra
    pub = requests.get(f"{API}/products").json()
    assert hidden["id"] not in {p["id"] for p in pub}


def test_toggle_active_publishes_and_hides():
    p = _create(is_active=False)
    r = requests.post(f"{API}/admin/products/{p['id']}/toggle-active",
                      headers=_h(ADMIN_TOKEN), json={})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True
    pub = {x["id"] for x in requests.get(f"{API}/products").json()}
    assert p["id"] in pub
    r = requests.post(f"{API}/admin/products/{p['id']}/toggle-active",
                      headers=_h(ADMIN_TOKEN), json={})
    assert r.json()["is_active"] is False
    pub = {x["id"] for x in requests.get(f"{API}/products").json()}
    assert p["id"] not in pub


def test_toggle_missing_product_404():
    r = requests.post(f"{API}/admin/products/no-existe/toggle-active",
                      headers=_h(ADMIN_TOKEN), json={})
    assert r.status_code == 404


def test_clients_cannot_manage():
    r = requests.get(f"{API}/admin/products", headers=_h(VIP_TOKEN))
    assert r.status_code == 403
    p = _create()
    r = requests.post(f"{API}/admin/products/{p['id']}/toggle-active",
                      headers=_h(VIP_TOKEN), json={})
    assert r.status_code == 403


def test_excel_products_activated_by_migration():
    db = _db()
    marker = db.settings.find_one({"id": "global"}, {"_id": 0})
    assert marker.get("excel_inventory_activated_at")
    assert db.products.count_documents(
        {"category": "mercadito", "is_active": False}) == 0
    maicena = db.products.find_one({"name": "Maicena"}, {"_id": 0})
    assert maicena["is_active"] is True
    # visibles en el marketplace público
    pub_names = {p["name"] for p in requests.get(f"{API}/products").json()}
    assert "Maicena" in pub_names
