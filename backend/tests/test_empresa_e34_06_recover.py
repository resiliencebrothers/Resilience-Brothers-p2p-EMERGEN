"""E34-06 — la compensación de una cancelación de envío Empresa NO debe depender
de que la Empresa abra GET /company/deliveries.

- La cancelación ADMIN reconcilia la solicitud inline (reembolso + devolución).
- Un worker recuperable reconcilia solicitudes antiguas/offline (incluso más
  allá de las 200 recientes), solo si la entrega está realmente cancelada.
- Idempotente: repetir no duplica efectos.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import BASE_URL, ADMIN_TOKEN  # noqa: E402
from services.company_delivery_recovery import (  # noqa: E402
    heal_cancelled_company_deliveries)
from services import company_delivery_billing as billing  # noqa: E402
from services import company_inventory as ci  # noqa: E402

API = f"{BASE_URL}/api"
CID = "user_test_e3406"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _q(v):
    return round(float(v or 0), 3)


def _loop():
    """Loop robusto para tests SÍNCRONOS aunque un test async previo lo cerrara."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _cleanup():
    db = _db()
    db.users.delete_one({"user_id": CID})
    db.products.delete_many({"company_id": CID})
    db.stores.delete_many({"company_id": CID})
    db.company_delivery_requests.delete_many({"company_id": CID})
    db.deliveries.delete_many({"ref_id": {"$regex": "^e3406"}})
    db.company_inventory_ops.delete_many({"company_id": CID})
    db.company_inventory_moves.delete_many({"company_id": CID})


def _seed(reqid, delivery_status="available", req_status="requested",
          created=None, with_store=True):
    """Siembra con EFECTOS DURADEROS REALES (R02): retiene la tarifa de verdad
    (débito) y reserva inventario de verdad (dispatch), de modo que el saldo y
    el stock reflejen un alta real a medio compensar. Producto con 2 uds en la
    tienda (stock 10, distribuido 2) → tras el dispatch queda stock 8/by_store 0;
    la reconciliación debe devolverlo a stock 10/by_store 2 y el saldo a 100."""
    db = _db()
    loop = _loop()
    sid = f"{reqid}-store"
    pid = f"{reqid}-prod"
    if with_store:
        db.stores.insert_one({"id": sid, "company_id": CID, "name": "T", "active": True})
    db.products.insert_one({
        "id": pid, "name": "P3406", "company_id": CID, "owner_id": CID,
        "stock": 10.0, "distributed": 2.0, "by_store": {sid: 2.0}, "is_active": True})
    db.users.update_one({"user_id": CID},
                        {"$set": {"vip_balances": {"USDT": 100.0}}}, upsert=True)
    # Retención REAL de tarifa (saldo 100 → 95) y reserva REAL (stock 10 → 8).
    assert loop.run_until_complete(billing.hold_fee(CID, reqid, 5)) == "applied"
    assert loop.run_until_complete(
        ci.dispatch_from_store(CID, pid, sid, 2.0, op_id=f"cdeliv:{reqid}")) == "applied"
    did = f"e3406-{uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "kind": "company_delivery", "ref_id": reqid,
        "status": delivery_status, "created_at": _now()})
    db.company_delivery_requests.insert_one({
        "id": reqid, "company_id": CID, "delivery_id": did, "status": req_status,
        "client_key": reqid,
        "product_id": pid, "origin_store_id": sid, "quantity": 2.0,
        "inv_reserved": True, "inv_returned": False,
        "fee_usdt": 5, "fee_status": "held",
        "created_at": created or _now()})
    return did, pid, sid


class TestE3406:
    def setup_method(self, _):
        _cleanup()

    def teardown_method(self, _):
        _cleanup()

    def test_admin_cancel_reconciles_without_user_get(self):
        db = _db()
        reqid = f"e3406A{uuid.uuid4().hex[:8]}"
        did, pid, sid = _seed(reqid, delivery_status="available")
        # Admin cancela (Empresa desconectada, sin GET /company/deliveries).
        r = requests.post(f"{API}/admin/deliveries/{did}/cancel",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"expected_status": "available", "expected_uid": None})
        assert r.status_code == 200, r.text
        # La solicitud quedó reconciliada SIN que la Empresa abriera su pantalla.
        req = db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert req["status"] == "cancelled"
        assert req["fee_status"] == "refunded"
        assert req["inv_returned"] is True
        p = db.products.find_one({"id": pid}, {"_id": 0})
        assert _q(p["stock"]) == 10.0
        assert _q((p.get("by_store") or {}).get(sid)) == 2.0  # restituido a la tienda

    def test_recoverer_heals_offline_cancelled_delivery(self):
        db = _db()
        reqid = f"e3406B{uuid.uuid4().hex[:8]}"
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        # Entrega YA cancelada pero solicitud sin reconciliar (nunca hubo GET).
        did, pid, sid = _seed(reqid, delivery_status="cancelled", created=old)
        # Control: otra solicitud cuya entrega sigue ACTIVA → NO debe tocarse.
        reqid_ctl = f"e3406C{uuid.uuid4().hex[:8]}"
        _seed(reqid_ctl, delivery_status="available")

        healed = _loop().run_until_complete(
            heal_cancelled_company_deliveries())
        assert healed >= 1

        req = db.company_delivery_requests.find_one({"id": reqid}, {"_id": 0})
        assert req["status"] == "cancelled" and req["fee_status"] == "refunded"
        assert req["inv_returned"] is True
        assert _q(db.products.find_one({"id": pid})["stock"]) == 10.0
        # El control NO se compensó (su entrega sigue activa).
        ctl = db.company_delivery_requests.find_one({"id": reqid_ctl}, {"_id": 0})
        assert ctl["status"] == "requested" and ctl["fee_status"] == "held"
        assert ctl["inv_returned"] is False

    def test_recoverer_is_idempotent(self):
        db = _db()
        reqid = f"e3406D{uuid.uuid4().hex[:8]}"
        did, pid, sid = _seed(reqid, delivery_status="cancelled")
        loop = _loop()
        loop.run_until_complete(heal_cancelled_company_deliveries())
        stock_after_first = _q(db.products.find_one({"id": pid})["stock"])
        # Segunda pasada: no vuelve a compensar (status ya cancelled) ni duplica stock.
        healed2 = loop.run_until_complete(heal_cancelled_company_deliveries())
        assert healed2 == 0
        assert _q(db.products.find_one({"id": pid})["stock"]) == stock_after_first == 10.0
