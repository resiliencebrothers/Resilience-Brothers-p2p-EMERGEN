"""IPV Fase 3 (incidencias) + Reposición/nivel objetivo — iter333.

- build_reorder_list: productos en/bajo mínimo con sugerencia hacia el objetivo.
- target-stock PATCH.
- Incidencias auto: venta_bajo_costo (al vender bajo costo), diferencia (al
  contar con descuadre) y su auto-resolución al autorizar el ajuste;
  conteo_pendiente (sync) y su resolución al contar.
- Ciclo de estado pendiente→en_revision→resuelta con traza.
- Permisos (vip 403).
"""
import os
import uuid
import asyncio

import requests
import pytest
from pymongo import MongoClient

from services.inventory import record_movement, build_reorder_list
from services.inventory_ipv import (record_physical_count,
                                     authorize_count_adjustment)
from services.inventory_incidents import (sync_pending_count_incidents,
                                           transition_incident, list_incidents)

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = {"session_token": "test_session_admin_X"}
VIP = {"session_token": "test_session_vip_X"}
ACTOR = {"user_id": "u_admin_test", "email": "admin.test@resilience.com"}


_LOOP = None


def _loop():
    # iter342: loop cacheado y siempre fijado como actual (ver test_iter330).
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)
    return _LOOP


@pytest.fixture
def prod():
    pid = f"TEST_IPV333_{uuid.uuid4().hex[:8]}"
    doc = {"id": pid, "name": "Prod Inc 333", "category": "Prueba",
           "is_active": True, "stock": 10, "cost_usd": 20.0, "price_usd": 30.0,
           "owner_id": ""}
    _db.products.insert_one(doc)
    yield doc
    _db.products.delete_one({"id": pid})
    _db.inventory_movements.delete_many({"product_id": pid})
    _db.inventory_counts.delete_many({"product_id": pid})
    _db.inventory_incidents.delete_many({"product_id": pid})


def _inc(product_id, itype):
    return _db.inventory_incidents.find_one(
        {"product_id": product_id, "type": itype}, {"_id": 0}, sort=[("created_at", -1)])


class TestReorder:
    def test_suggested_to_target(self, prod):
        _db.products.update_one({"id": prod["id"]},
                                {"$set": {"stock": 2, "min_stock": 5, "target_stock": 12}})
        rows = _loop().run_until_complete(build_reorder_list())
        r = next((x for x in rows if x["product_id"] == prod["id"]), None)
        assert r is not None
        assert r["min_stock"] == 5 and r["target"] == 12
        assert r["suggested"] == 10  # 12 - 2
        assert r["restock_cost"] == 200.0  # 10 * 20

    def test_above_min_not_listed(self, prod):
        _db.products.update_one({"id": prod["id"]},
                                {"$set": {"stock": 50, "min_stock": 5}})
        rows = _loop().run_until_complete(build_reorder_list())
        assert all(x["product_id"] != prod["id"] for x in rows)

    def test_patch_target(self, prod):
        r = requests.patch(f"{API}/admin/inventory/products/{prod['id']}/target-stock",
                           json={"target_stock": 30}, cookies=ADMIN)
        assert r.status_code == 200 and r.json()["target_stock"] == 30
        assert _db.products.find_one({"id": prod["id"]})["target_stock"] == 30


class TestVentaBajoCosto:
    def test_sale_below_cost_creates_incident(self, prod):
        # vende 1 ud a 5 CUP con costo 20 → pérdida 15.
        _loop().run_until_complete(record_movement(
            product=prod, mtype="venta", quantity=1, unit_price=5.0,
            unit_cost=20.0, source="test", actor=ACTOR))
        inc = _inc(prod["id"], "venta_bajo_costo")
        assert inc is not None
        assert inc["status"] == "pendiente"
        assert inc["amount"] == 15.0

    def test_sale_at_cost_no_incident(self, prod):
        _loop().run_until_complete(record_movement(
            product=prod, mtype="venta", quantity=1, unit_price=25.0,
            unit_cost=20.0, source="test", actor=ACTOR))
        assert _inc(prod["id"], "venta_bajo_costo") is None


class TestDiferenciaLifecycle:
    def test_count_diff_then_authorize_resolves(self, prod):
        _db.inventory_counts.delete_many({"product_id": prod["id"]})
        # cuenta 7 vs 10 teórico → diferencia -3 → incidencia diferencia.
        fresh = _db.products.find_one({"id": prod["id"]}, {"_id": 0})
        count = _loop().run_until_complete(
            record_physical_count(fresh, 7, actor=ACTOR))
        inc = _inc(prod["id"], "diferencia")
        assert inc is not None and inc["status"] == "pendiente"
        # autorizar el ajuste → la incidencia se auto-resuelve.
        _loop().run_until_complete(authorize_count_adjustment(
            count["id"], document="DOC-1", note="ok", actor=ACTOR))
        inc2 = _inc(prod["id"], "diferencia")
        assert inc2["status"] == "resuelta" and inc2["auto_resolved"] is True


class TestConteoPendiente:
    def test_sync_creates_and_count_resolves(self, prod):
        res = _loop().run_until_complete(sync_pending_count_incidents())
        assert res["created"] >= 1
        inc = _inc(prod["id"], "conteo_pendiente")
        assert inc is not None and inc["status"] == "pendiente"
        # al contar el producto, la incidencia de conteo pendiente se resuelve.
        fresh = _db.products.find_one({"id": prod["id"]}, {"_id": 0})
        _loop().run_until_complete(record_physical_count(fresh, 10, actor=ACTOR))
        inc2 = _inc(prod["id"], "conteo_pendiente")
        assert inc2["status"] == "resuelta"


class TestTransition:
    def test_manual_lifecycle(self, prod):
        _loop().run_until_complete(record_movement(
            product=prod, mtype="venta", quantity=1, unit_price=5.0,
            unit_cost=20.0, source="test", actor=ACTOR))
        inc = _inc(prod["id"], "venta_bajo_costo")
        upd = _loop().run_until_complete(transition_incident(
            inc["id"], "en_revision", "revisando", ACTOR))
        assert upd["status"] == "en_revision"
        upd2 = _loop().run_until_complete(transition_incident(
            inc["id"], "resuelta", "justificada (promo)", ACTOR))
        assert upd2["status"] == "resuelta"
        assert upd2["auto_resolved"] is False
        assert any(h["status"] == "en_revision" for h in upd2["history"])


class TestPermissions:
    def test_incidents_denied_for_vip(self):
        r = requests.get(f"{API}/admin/inventory/incidents", cookies=VIP)
        assert r.status_code == 403

    def test_incidents_admin_ok(self):
        r = requests.get(f"{API}/admin/inventory/incidents", cookies=ADMIN)
        assert r.status_code == 200
        assert "summary" in r.json()
