"""E34-05 (HTTP) — cancelación de envío Empresa vía endpoint real:
- tienda borrada → inventario vuelve al central, inv_returned=True.
- producto borrado → NO se sella éxito, inv_returned=False + incidencia.
- borrar producto con reserva activa → 409.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
CID = "user_test_e3405http"
TOK = "test_session_e3405http_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}


def _seed_session():
    db = _db()
    db.users.update_one({"user_id": CID}, {"$set": {
        "user_id": CID, "email": "e3405@example.com", "name": "Empresa 3405",
        "role": "empresa", "account_status": "active", "email_verified": True,
        "phone_verified": True, "phone": "+5350003405"}}, upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": TOK},
        {"$set": {"session_token": TOK, "user_id": CID, "expires_at": exp}}, upsert=True)


def _cleanup():
    db = _db()
    db.products.delete_many({"company_id": CID})
    db.stores.delete_many({"company_id": CID})
    db.company_delivery_requests.delete_many({"company_id": CID})
    db.deliveries.delete_many({"ref_id": {"$regex": "^e3405"}})
    db.company_inventory_ops.delete_many({"company_id": CID})
    db.company_inventory_moves.delete_many({"company_id": CID})


def _q(v):
    return round(float(v or 0), 3)


def _seed_reserved_delivery(reqid, pid, sid, qty=2.0):
    """Siembra un producto YA reservado (stock descontado de la tienda) + una
    entrega available + la solicitud en 'requested' con inv_reserved=True."""
    db = _db()
    # Estado POST-reserva: total 10 → 8, distributed 2 → 0, by_store sid 0.
    db.products.insert_one({
        "id": pid, "name": "P3405", "company_id": CID, "owner_id": CID,
        "stock": 8.0, "distributed": 0.0, "by_store": {sid: 0.0}, "is_active": True})
    did = f"e3405-del-{uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "kind": "company_delivery", "ref_id": reqid,
        "status": "available", "created_at": datetime.now(timezone.utc).isoformat()})
    db.company_delivery_requests.insert_one({
        "id": reqid, "company_id": CID, "delivery_id": did, "status": "requested",
        "product_id": pid, "origin_store_id": sid, "quantity": qty,
        "inv_reserved": True, "inv_returned": False,
        "fee_usdt": 0, "fee_status": "none",
        "created_at": datetime.now(timezone.utc).isoformat()})
    return did


class TestE3405Http:
    def setup_method(self, _):
        _cleanup(); _seed_session()

    def teardown_method(self, _):
        _cleanup()

    def test_cancel_after_store_deleted_returns_to_central(self):
        db = _db()
        sid = str(uuid.uuid4()); pid = str(uuid.uuid4()); reqid = f"e3405-A-{uuid.uuid4().hex[:8]}"
        # La tienda NO existe (fue cerrada/borrada antes de cancelar).
        _seed_reserved_delivery(reqid, pid, sid)
        r = requests.post(f"{API}/company/deliveries/{reqid}/cancel", headers=_hdr())
        assert r.status_code == 200, r.text
        req = db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert req["status"] == "cancelled"
        assert req["inv_returned"] is True
        p = db.products.find_one({"id": pid}, {"_id": 0})
        # Mercancía en el central: total 10, distributed 0, SIN by_store huérfano.
        assert _q(p["stock"]) == 10.0
        assert _q(p.get("distributed")) == 0.0
        assert _q((p.get("by_store") or {}).get(sid, 0)) == 0.0

    def test_cancel_after_product_deleted_flags_incident(self):
        db = _db()
        sid = str(uuid.uuid4()); pid = str(uuid.uuid4()); reqid = f"e3405-B-{uuid.uuid4().hex[:8]}"
        did = _seed_reserved_delivery(reqid, pid, sid)
        db.stores.insert_one({"id": sid, "company_id": CID, "name": "T", "active": True})
        db.products.delete_one({"id": pid})  # producto borrado antes de cancelar
        r = requests.post(f"{API}/company/deliveries/{reqid}/cancel", headers=_hdr())
        assert r.status_code == 200, r.text
        req = db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        # NO se sella éxito: queda pendiente + incidencia.
        assert req["inv_returned"] is False
        assert req.get("inv_return_incident") is True
        d = db.deliveries.find_one({"id": did}, {"_id": 0})
        assert d.get("origin_conflict") is not None

    def test_delete_product_with_active_reservation_blocked(self):
        sid = str(uuid.uuid4()); pid = str(uuid.uuid4()); reqid = f"e3405-C-{uuid.uuid4().hex[:8]}"
        _seed_reserved_delivery(reqid, pid, sid)
        r = requests.delete(f"{API}/company/products/{pid}", headers=_hdr())
        assert r.status_code == 409, r.text
        assert _db().products.find_one({"id": pid}) is not None
