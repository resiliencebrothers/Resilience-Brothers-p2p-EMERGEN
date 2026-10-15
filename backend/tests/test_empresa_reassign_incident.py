"""Reasignar inventario de una incidencia Empresa a una tienda existente.

Flujo: un envío cancelado cuyo producto/tienda dejó inventario PENDIENTE
(inv_return_incident) se puede reasignar a una tienda activa de la empresa:
la cantidad se suma al inventario de esa tienda y la incidencia se resuelve.
Si el producto ya no existe, la reasignación NO está permitida (409).
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
CID = "user_test_reassign"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _q(v):
    return round(float(v or 0), 3)


def _cleanup():
    db = _db()
    db.products.delete_many({"company_id": CID})
    db.stores.delete_many({"company_id": CID})
    db.company_delivery_requests.delete_many({"company_id": CID})
    db.deliveries.delete_many({"ref_id": {"$regex": "^reassign"}})
    db.company_inventory_ops.delete_many({"company_id": CID})
    db.company_inventory_moves.delete_many({"company_id": CID})


def _seed(with_product=True):
    """Incidencia con inventario pendiente: solicitud cancelada, inv_reserved,
    inv_returned False, inv_return_incident True + entrega con origin_conflict."""
    db = _db()
    reqid = f"reassign_{uuid.uuid4().hex[:10]}"
    sid = f"{reqid}-store"
    pid = f"{reqid}-prod"
    db.stores.insert_one({"id": sid, "company_id": CID, "name": "Tienda Activa",
                          "is_active": True})
    if with_product:
        db.products.insert_one({
            "id": pid, "name": "ProdReasignar", "company_id": CID, "owner_id": CID,
            "stock": 5.0, "distributed": 0.0, "by_store": {sid: 0.0}, "is_active": True})
    did = f"reassign-del-{uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "kind": "company_delivery", "ref_id": reqid, "status": "delivered",
        "client_name": "Reassign",
        "origin_conflict": {"kind": "company_delivery", "ref_id": reqid,
                            "note": "no se pudo devolver", "at": _now()},
        "created_at": _now()})
    db.company_delivery_requests.insert_one({
        "id": reqid, "company_id": CID, "delivery_id": did, "status": "cancelled",
        "client_key": reqid, "product_id": pid, "origin_store_id": sid, "quantity": 3.0,
        "inv_reserved": True, "inv_returned": False, "inv_return_incident": True,
        "inv_return_incident_reason": "not_found", "fee_usdt": 0, "fee_status": "none",
        "created_at": _now()})
    return reqid, did, pid, sid


class TestReassignIncidentInventory:
    def setup_method(self, _):
        _cleanup()

    def teardown_method(self, _):
        _cleanup()

    def test_incident_lists_reassign_info(self):
        reqid, did, pid, sid = _seed()
        r = requests.get(f"{API}/admin/delivery-incidents", headers=_hdr())
        assert r.status_code == 200, r.text
        row = next((x for x in r.json() if x["id"] == did), None)
        assert row is not None
        rz = row.get("reassign") or {}
        assert rz.get("pending") is True and rz.get("product_exists") is True
        assert _q(rz.get("quantity")) == 3.0
        assert any(s["id"] == sid for s in rz.get("stores", []))

    def test_reassign_adds_stock_to_store_and_resolves(self):
        db = _db()
        reqid, did, pid, sid = _seed()
        r = requests.post(f"{API}/admin/delivery-incidents/{did}/reassign-inventory",
                          headers=_hdr(), json={"store_id": sid, "note": "ajuste manual"})
        assert r.status_code == 200, r.text
        # La cantidad (3) se sumó a la tienda elegida: total 5→8, by_store 0→3.
        p = db.products.find_one({"id": pid}, {"_id": 0})
        assert _q(p["stock"]) == 8.0
        assert _q((p.get("by_store") or {}).get(sid)) == 3.0
        assert _q(p.get("distributed")) == 3.0
        # Solicitud marcada como devuelta; incidencia resuelta.
        req = db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert req["inv_returned"] is True
        d = db.deliveries.find_one({"id": did}, {"_id": 0})
        assert d["origin_conflict"]["resolved"] is True
        # Ya no aparece entre las abiertas.
        openlist = requests.get(f"{API}/admin/delivery-incidents", headers=_hdr()).json()
        assert did not in {x["id"] for x in openlist}

    def test_reassign_idempotent_no_double_stock(self):
        db = _db()
        reqid, did, pid, sid = _seed()
        r1 = requests.post(f"{API}/admin/delivery-incidents/{did}/reassign-inventory",
                           headers=_hdr(), json={"store_id": sid})
        assert r1.status_code == 200, r1.text
        # Segundo intento: la incidencia ya está resuelta → 404 (sin doble stock).
        r2 = requests.post(f"{API}/admin/delivery-incidents/{did}/reassign-inventory",
                           headers=_hdr(), json={"store_id": sid})
        assert r2.status_code == 404, r2.text
        assert _q(db.products.find_one({"id": pid})["stock"]) == 8.0

    def test_reassign_blocked_when_product_deleted(self):
        reqid, did, pid, sid = _seed(with_product=False)
        r = requests.post(f"{API}/admin/delivery-incidents/{did}/reassign-inventory",
                          headers=_hdr(), json={"store_id": sid})
        assert r.status_code == 409, r.text
        assert "producto" in (r.json().get("detail") or "").lower()
