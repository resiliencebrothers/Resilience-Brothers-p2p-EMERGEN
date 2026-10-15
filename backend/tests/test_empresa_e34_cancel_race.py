"""E34-01 — la cancelación de Empresa NO debe devolver fondos/stock sin ganar la
cancelación de la entrega.

Antes: el handler leía el estado de la entrega y luego llamaba a un helper
genérico cuyo filtro permitía accepted/on_the_way; además el reembolso, el
retorno de stock y el sello de solicitud corrían aunque la escritura de
cancelación NO hubiese ganado. Ahora la transición es ATÓMICA y limitada a
available/assigned, y las compensaciones dependen de una cancelación ganada
(o de evidencia duradera para reintentos).

Simulamos el estado "en el momento de la escritura" fijando el estado de la
entrega antes de llamar a /company/deliveries/{id}/cancel.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa_e34"
EMP_TOKEN = "test_session_empresa_e34_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed():
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa.e34@example.com", "name": "Empresa E34",
        "role": "empresa", "account_status": "active", "email_verified": True,
        "phone_verified": True, "phone": "+5350000777",
        "vip_balances": {"USDT": 100.0}}}, upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)
    db.settings.update_one({"id": "global"},
        {"$set": {"company_delivery_fee_usdt": 5}}, upsert=True)


def _cleanup():
    db = _db()
    rids = [r["id"] for r in db.company_delivery_requests.find({"company_id": EMP_ID}, {"id": 1})]
    db.deliveries.delete_many({"kind": "company_delivery", "ref_id": {"$in": rids}})
    db.company_delivery_requests.delete_many({"company_id": EMP_ID})
    db.products.delete_many({"company_id": EMP_ID})
    db.stores.delete_many({"company_id": EMP_ID})
    db.company_inventory_moves.delete_many({"company_id": EMP_ID})
    db.company_inventory_ops.delete_many({"company_id": EMP_ID})


def _mk_store():
    db = _db()
    sid = str(uuid.uuid4())
    db.stores.insert_one({"id": sid, "company_id": EMP_ID, "name": "Tienda E34",
                          "address": "x", "active": True})
    return sid


def _mk_product(store_id, by=10):
    db = _db()
    pid = str(uuid.uuid4())
    db.products.insert_one({
        "id": pid, "name": "Producto E34", "category": "general", "price_usd": 1.0,
        "cost_usd": 0.0, "stock": float(by), "distributed": float(by),
        "by_store": {store_id: float(by)}, "is_active": True,
        "owner_id": EMP_ID, "company_id": EMP_ID, "approval_status": "approved",
        "unit": "unidad"})
    return pid


def _create_request(pid, sid, qty=3):
    r = requests.post(f"{API}/company/deliveries", headers=_hdr(), json={
        "receiver_name": "Juan Cliente", "receiver_phone": "+5355551234",
        "delivery_address": "Calle 10 #20", "province": "La Habana",
        "municipality": "Plaza", "note": "x",
        "product_id": pid, "origin_store_id": sid, "quantity": qty}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _bal():
    u = _db().users.find_one({"user_id": EMP_ID}, {"_id": 0, "vip_balances": 1})
    return round(float((u.get("vip_balances") or {}).get("USDT") or 0), 2)


def _shelf(pid, sid):
    p = _db().products.find_one({"id": pid}, {"_id": 0, "by_store": 1})
    return round(float((p.get("by_store") or {}).get(sid) or 0), 3)


def _req_status(rid):
    return _db().company_delivery_requests.find_one({"id": rid}, {"_id": 0, "status": 1})["status"]


def _set_delivery_status(did, status):
    _db().deliveries.update_one({"id": did}, {"$set": {"status": status}})


class TestCompanyCancelRace:
    def setup_method(self, _):
        _seed(); _cleanup()
        _db().users.update_one({"user_id": EMP_ID}, {"$set": {"vip_balances.USDT": 100.0}})

    def teardown_method(self, _):
        _cleanup()

    def _fresh(self):
        sid = _mk_store(); pid = _mk_product(sid)
        body = _create_request(pid, sid, qty=3)
        # tras crear: tarifa retenida (100→95) y 3 uds despachadas (10→7)
        assert _bal() == 95.0
        assert _shelf(pid, sid) == 7
        return body["id"], body["delivery_id"], pid, sid

    def test_available_cancel_wins_and_compensates(self):
        rid, did, pid, sid = self._fresh()
        r = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r.status_code == 200, r.text
        assert _bal() == 100.0                 # tarifa reembolsada
        assert _shelf(pid, sid) == 10          # stock devuelto a la tienda
        assert _req_status(rid) == "cancelled"
        assert _db().deliveries.find_one({"id": did})["status"] == "cancelled"

    def test_accepted_before_write_conflicts_without_effects(self):
        rid, did, pid, sid = self._fresh()
        _set_delivery_status(did, "accepted")
        r = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r.status_code == 409, r.text
        assert _bal() == 95.0                  # SIN reembolso
        assert _shelf(pid, sid) == 7           # SIN devolución de stock
        assert _req_status(rid) != "cancelled"
        assert _db().deliveries.find_one({"id": did})["status"] == "accepted"

    def test_delivered_before_write_conflicts_without_effects(self):
        # Escenario clave del reporte: entrega 'delivered' entre lectura y
        # escritura; antes devolvía éxito + reembolso + retorno de mercancía.
        rid, did, pid, sid = self._fresh()
        _set_delivery_status(did, "delivered")
        r = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r.status_code == 409, r.text
        assert _bal() == 95.0
        assert _shelf(pid, sid) == 7
        assert _req_status(rid) != "cancelled"
        assert _db().deliveries.find_one({"id": did})["status"] == "delivered"

    def test_confirmed_before_write_conflicts_without_effects(self):
        rid, did, pid, sid = self._fresh()
        _set_delivery_status(did, "confirmed")
        r = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r.status_code == 409, r.text
        assert _bal() == 95.0 and _shelf(pid, sid) == 7
        assert _req_status(rid) != "cancelled"

    def test_assigned_cancel_wins(self):
        rid, did, pid, sid = self._fresh()
        _set_delivery_status(did, "assigned")
        r = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r.status_code == 200, r.text
        assert _bal() == 100.0 and _shelf(pid, sid) == 10
        assert _req_status(rid) == "cancelled"

    def test_crash_retry_single_economic_effect(self):
        # Caída entre la cancelación (ganada) y las compensaciones: la entrega
        # quedó 'cancelled' pero la solicitud sigue sin sellar. El reintento
        # completa UN solo efecto; un segundo reintento NO vuelve a reembolsar.
        rid, did, pid, sid = self._fresh()
        _set_delivery_status(did, "cancelled")  # prior win, durable evidence
        r1 = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r1.status_code == 200, r1.text
        assert _bal() == 100.0 and _shelf(pid, sid) == 10
        assert _req_status(rid) == "cancelled"
        r2 = requests.post(f"{API}/company/deliveries/{rid}/cancel", headers=_hdr())
        assert r2.status_code == 200
        assert _bal() == 100.0          # sin doble reembolso
        assert _shelf(pid, sid) == 10   # sin doble devolución
