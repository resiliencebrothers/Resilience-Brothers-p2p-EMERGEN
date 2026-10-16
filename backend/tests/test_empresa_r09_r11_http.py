"""R09 — contrato de idempotencia del alta de envíos Empresa: una misma
`client_key` con PAYLOAD distinto NO reutiliza en silencio la solicitud anterior
(409 de conflicto); misma clave + mismo payload es idempotente.

R11 — la reasignación de inventario de una incidencia usa el campo REAL de la
tienda (`active`), de modo que una tienda `active=false` NO se acepta como destino.
"""
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import BASE_URL, ADMIN_TOKEN  # noqa: E402

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa_r09"
EMP_TOKEN = "test_session_empresa_r09_X"
R11_CID = "user_test_empresa_r11"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _q(v):
    return round(float(v or 0), 3)


# --------------------------------------------------------------------------- R09
def _seed_company():
    db = _db()
    now = datetime.now(timezone.utc)
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "r09@example.com", "name": "Empresa R09",
        "role": "empresa", "account_status": "active", "account_type": "business",
        "email_verified": True, "phone_verified": True,
        "vip_balances": {"USDT": 100.0}}}, upsert=True)
    db.user_sessions.update_one({"session_token": EMP_TOKEN}, {"$set": {
        "session_token": EMP_TOKEN, "user_id": EMP_ID,
        "expires_at": (now + timedelta(days=30)).isoformat()}}, upsert=True)
    db.company_delivery_requests.delete_many({"company_id": EMP_ID})


def _clean_company():
    db = _db()
    db.company_delivery_requests.delete_many({"company_id": EMP_ID})
    db.users.delete_one({"user_id": EMP_ID})
    db.user_sessions.delete_one({"session_token": EMP_TOKEN})
    db.deliveries.delete_many({"kind": "company_delivery", "created_by": EMP_ID})


def _ship_body(key, address):
    return {"receiver_name": "Juan", "receiver_phone": "+5350000000",
            "delivery_address": address, "province": "La Habana",
            "municipality": "Centro", "note": "Envío R09", "client_key": key}


def test_r09_same_key_different_payload_conflicts():
    _seed_company()
    try:
        key = f"R09-{uuid.uuid4().hex[:8]}"
        r1 = requests.post(f"{API}/company/deliveries", headers=_hdr(EMP_TOKEN),
                           json=_ship_body(key, "Calle 1 #100"))
        assert r1.status_code == 200, r1.text
        # Misma clave, MISMA carga → idempotente (misma solicitud, sin duplicar).
        r2 = requests.post(f"{API}/company/deliveries", headers=_hdr(EMP_TOKEN),
                           json=_ship_body(key, "Calle 1 #100"))
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == r1.json()["id"]
        # Misma clave, carga DISTINTA (otra dirección) → 409 de conflicto.
        r3 = requests.post(f"{API}/company/deliveries", headers=_hdr(EMP_TOKEN),
                           json=_ship_body(key, "OTRA Calle 999"))
        assert r3.status_code == 409, r3.text
        # Solo UNA solicitud creada para esa clave.
        db = _db()
        n = db.company_delivery_requests.count_documents(
            {"company_id": EMP_ID, "client_key": key})
        assert n == 1
    finally:
        _clean_company()


# --------------------------------------------------------------------------- R11
def _seed_incident(store_active, store_has_is_active=False):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    reqid = f"r11-{uuid.uuid4().hex[:8]}"
    pid = f"{reqid}-prod"
    sid = f"{reqid}-store"
    db.products.insert_one({
        "id": pid, "name": "P-R11", "company_id": R11_CID, "owner_id": R11_CID,
        "stock": 8.0, "distributed": 0.0, "by_store": {}, "is_active": True})
    store = {"id": sid, "company_id": R11_CID, "name": "Tienda R11", "active": store_active}
    if store_has_is_active:
        store["is_active"] = True
    db.stores.insert_one(store)
    db.company_delivery_requests.insert_one({
        "id": reqid, "company_id": R11_CID, "product_id": pid,
        "origin_store_id": "gone", "quantity": 2.0,
        "inv_return_incident": True, "inv_returned": False,
        "inv_return_incident_reason": "not_found", "status": "cancelled",
        "created_at": now})
    did = f"r11d-{uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "kind": "company_delivery", "ref_id": reqid,
        "status": "delivered", "created_at": now,
        "origin_conflict": {"resolved": False, "kind": "company_delivery",
                            "ref_id": reqid, "at": now,
                            "note": "No se pudo devolver el inventario"}})
    return did, pid, sid


def _clean_r11():
    db = _db()
    db.products.delete_many({"company_id": R11_CID})
    db.stores.delete_many({"company_id": R11_CID})
    db.company_delivery_requests.delete_many({"company_id": R11_CID})
    db.deliveries.delete_many({"ref_id": {"$regex": "^r11-"}})


def test_r11_inactive_store_rejected_by_real_field():
    _clean_r11()
    try:
        did, pid, sid = _seed_incident(store_active=False)
        r = requests.post(
            f"{API}/admin/delivery-incidents/{did}/reassign-inventory",
            headers=_hdr(ADMIN_TOKEN), json={"store_id": sid})
        # active=false → NO debe aceptarse como destino (antes pasaba por usar is_active).
        assert r.status_code == 400, r.text
        db = _db()
        p = db.products.find_one({"id": pid}, {"_id": 0})
        assert _q((p.get("by_store") or {}).get(sid)) == 0.0  # no se asignó nada
    finally:
        _clean_r11()


def test_r11_active_store_accepts_reassignment_once():
    _clean_r11()
    try:
        did, pid, sid = _seed_incident(store_active=True)
        r = requests.post(
            f"{API}/admin/delivery-incidents/{did}/reassign-inventory",
            headers=_hdr(ADMIN_TOKEN), json={"store_id": sid})
        assert r.status_code == 200, r.text
        db = _db()
        p = db.products.find_one({"id": pid}, {"_id": 0})
        assert _q((p.get("by_store") or {}).get(sid)) == 2.0  # restituido una vez
        assert _q(p["stock"]) == 10.0
    finally:
        _clean_r11()
