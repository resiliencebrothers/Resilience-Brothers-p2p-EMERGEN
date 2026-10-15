"""Empresa Fase 4 (EMP-04) — solicitar mensajería (Resilience asigna mensajero).

- La Empresa crea una solicitud de envío que entra al POOL de Resilience
  (deliveries, status 'available', sin mensajero). La Empresa NO asigna.
- Opcionalmente despacha un producto DESDE una tienda: descuenta esa tienda.
- Cancelar (por la Empresa) o reconciliar (si Resilience cancela) DEVUELVE el
  inventario reservado exactamente una vez.
- La Empresa NO tiene permiso para asignar mensajeros (403 en el endpoint admin).
"""
import os
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa04"
EMP_TOKEN = "test_session_empresa04_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=EMP_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _seed():
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa4.test@example.com",
        "name": "Empresa Envíos Test", "role": "empresa", "account_status": "active",
        "email_verified": True, "phone_verified": True, "phone": "+5350000444"}},
        upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)
    # Fase 4 asume mensajería gratuita: fija la tarifa global en 0 (evita que
    # el ciclo económico, configurable por el admin, afecte estas pruebas).
    db.settings.update_one({"id": "global"},
        {"$set": {"company_delivery_fee_usdt": 0}}, upsert=True)


def _cleanup():
    db = _db()
    rids = [r["id"] for r in db.company_delivery_requests.find({"company_id": EMP_ID}, {"id": 1})]
    db.deliveries.delete_many({"kind": "company_delivery", "ref_id": {"$in": rids}})
    db.company_delivery_requests.delete_many({"company_id": EMP_ID})
    db.products.delete_many({"company_id": EMP_ID})
    db.stores.delete_many({"company_id": EMP_ID})
    db.company_inventory_moves.delete_many({"company_id": EMP_ID})


def _recipient(**extra):
    base = {"receiver_name": "Juan Cliente", "receiver_phone": "+5355551234",
            "delivery_address": "Calle 10 #20, Vedado", "province": "La Habana"}
    base.update(extra)
    return base


def test_plain_request_enters_pool_without_courier():
    _seed(); _cleanup()
    try:
        r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                          json=_recipient(note="Documentos"), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        did = body["delivery_id"]
        assert body["delivery_status"] == "available"
        # entra al pool de Resilience sin mensajero asignado
        d = _db().deliveries.find_one({"id": did})
        assert d["kind"] == "company_delivery"
        assert d["status"] == "available"
        assert d.get("courier_id") in (None, "")
        # la Empresa lo ve en su lista
        lst = requests.get(f"{API}/company/deliveries", headers=_hdr(), timeout=15).json()
        assert did in [x["delivery_id"] for x in lst]
    finally:
        _cleanup()


def test_request_from_store_decrements_and_cancel_returns():
    _seed(); _cleanup()
    try:
        pid = requests.post(f"{API}/company/products", headers=_hdr(), json={
            "name": "Caja Ron", "price_usd": 9.0, "stock": 0}, timeout=15).json()["id"]
        sid = requests.post(f"{API}/company/stores", headers=_hdr(), json={
            "name": "Tienda Envíos", "address": "Dir larga tienda"}, timeout=15).json()["id"]
        requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                      json={"product_id": pid, "qty": 20}, timeout=15)
        requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                      json={"product_id": pid, "store_id": sid, "qty": 12}, timeout=15)

        # solicitar envío despachando 5 desde la tienda
        r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                          json=_recipient(product_id=pid, origin_store_id=sid, quantity=5),
                          timeout=15)
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]

        def _store_qty():
            rows = requests.get(f"{API}/company/inventory", headers=_hdr(), timeout=15).json()
            row = next(x for x in rows if x["product_id"] == pid)
            by = {s["store_id"]: s["qty"] for s in row["stores"]}
            return row["total"], row["central"], by.get(sid, 0)

        total, central, a = _store_qty()
        assert total == 15 and central == 8 and a == 7  # 12-5=7, total 20-5=15, central 8

        # cancelar por la Empresa → devuelve el inventario
        c = requests.post(f"{API}/company/deliveries/{req_id}/cancel", headers=_hdr(), timeout=15)
        assert c.status_code == 200, c.text
        total, central, a = _store_qty()
        assert total == 20 and central == 8 and a == 12  # devuelto

        # cancelar de nuevo es idempotente
        c2 = requests.post(f"{API}/company/deliveries/{req_id}/cancel", headers=_hdr(), timeout=15)
        assert c2.status_code == 200
        total, central, a = _store_qty()
        assert total == 20 and a == 12  # sin doble devolución
    finally:
        _cleanup()


def test_admin_cancel_is_reconciled_on_read():
    _seed(); _cleanup()
    try:
        pid = requests.post(f"{API}/company/products", headers=_hdr(), json={
            "name": "Paquete", "price_usd": 5.0, "stock": 0}, timeout=15).json()["id"]
        sid = requests.post(f"{API}/company/stores", headers=_hdr(), json={
            "name": "T Env", "address": "Dir larga env"}, timeout=15).json()["id"]
        requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                      json={"product_id": pid, "qty": 10}, timeout=15)
        requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                      json={"product_id": pid, "store_id": sid, "qty": 10}, timeout=15)
        r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                          json=_recipient(product_id=pid, origin_store_id=sid, quantity=4),
                          timeout=15).json()
        did = r["delivery_id"]
        # Resilience (admin) cancela la entrega (MEN22: estado + ciclo observados)
        db = _db()
        d = db.deliveries.find_one({"id": did})
        ac = requests.post(f"{API}/admin/deliveries/{did}/cancel", headers=_hdr(ADMIN_TOKEN),
                           json={"expected_status": d["status"],
                                 "expected_uid": d.get("assignment_uid")}, timeout=15)
        assert ac.status_code == 200, ac.text
        # al listar, la Empresa reconcilia y recupera el inventario
        lst = requests.get(f"{API}/company/deliveries", headers=_hdr(), timeout=15).json()
        row = next(x for x in lst if x["delivery_id"] == did)
        assert row["delivery_status"] == "cancelled"
        rows = requests.get(f"{API}/company/inventory", headers=_hdr(), timeout=15).json()
        prow = next(x for x in rows if x["product_id"] == pid)
        by = {s["store_id"]: s["qty"] for s in prow["stores"]}
        assert prow["total"] == 10 and by.get(sid) == 10  # devuelto
    finally:
        _cleanup()


def test_empresa_cannot_assign_courier():
    _seed(); _cleanup()
    try:
        did = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                            json=_recipient(note="x"), timeout=15).json()["delivery_id"]
        # la Empresa NO tiene permiso para asignar mensajeros
        r = requests.post(f"{API}/admin/deliveries/{did}/assign", headers=_hdr(),
                          json={"courier_id": "whatever"}, timeout=15)
        assert r.status_code == 403, r.text
    finally:
        _cleanup()
