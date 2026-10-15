"""E34-02 (end-to-end HTTP) — alta de envío IDEMPOTENTE: la misma client_key no
duplica solicitud, cargo ni reserva; los fallos (saldo/stock) no dejan efectos."""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa_e3402"
EMP_TOKEN = "test_session_empresa_e3402_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed(balance=100.0):
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa.e3402@example.com", "name": "Empresa E3402",
        "role": "empresa", "account_status": "active", "email_verified": True,
        "phone_verified": True, "phone": "+5350000999",
        "vip_balances": {"USDT": balance}}}, upsert=True)
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
    db.company_inventory_ops.delete_many({"company_id": EMP_ID})


def _mk_store():
    sid = str(uuid.uuid4())
    _db().stores.insert_one({"id": sid, "company_id": EMP_ID, "name": "Tienda E3402",
                             "address": "x", "active": True})
    return sid


def _mk_product(sid, by=10):
    pid = str(uuid.uuid4())
    _db().products.insert_one({
        "id": pid, "name": "Prod E3402", "category": "general", "price_usd": 1.0,
        "cost_usd": 0.0, "stock": float(by), "distributed": float(by),
        "by_store": {sid: float(by)}, "is_active": True, "owner_id": EMP_ID,
        "company_id": EMP_ID, "approval_status": "approved", "unit": "unidad"})
    return pid


def _bal():
    u = _db().users.find_one({"user_id": EMP_ID}, {"_id": 0, "vip_balances": 1})
    return round(float((u.get("vip_balances") or {}).get("USDT") or 0), 2)


def _shelf(pid, sid):
    p = _db().products.find_one({"id": pid}, {"_id": 0, "by_store": 1})
    return round(float((p.get("by_store") or {}).get(sid) or 0), 3)


def _n_requests():
    return _db().company_delivery_requests.count_documents({"company_id": EMP_ID})


def _n_deliveries():
    rids = [r["id"] for r in _db().company_delivery_requests.find({"company_id": EMP_ID}, {"id": 1})]
    return _db().deliveries.count_documents({"kind": "company_delivery", "ref_id": {"$in": rids}})


def _body(key, sid=None, pid=None, qty=None):
    b = {"receiver_name": "Juan", "receiver_phone": "+5355551234",
         "delivery_address": "Calle 10 #20", "province": "La Habana",
         "municipality": "Plaza", "note": "x", "client_key": key}
    if pid:
        b.update({"product_id": pid, "origin_store_id": sid, "quantity": qty})
    return b


class TestIdempotentCreate:
    def setup_method(self, _):
        _seed(); _cleanup(); _seed()

    def teardown_method(self, _):
        _cleanup()

    def test_same_key_does_not_duplicate(self):
        sid = _mk_store(); pid = _mk_product(sid, 10)
        key = str(uuid.uuid4())
        r1 = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                           json=_body(key, sid, pid, 3))
        assert r1.status_code == 200, r1.text
        assert _bal() == 95.0 and _shelf(pid, sid) == 7
        assert _n_requests() == 1 and _n_deliveries() == 1
        first_id = r1.json()["id"]
        # repetir el MISMO envío (reintento por pérdida de respuesta)
        r2 = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                           json=_body(key, sid, pid, 3))
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == first_id            # misma solicitud
        assert _bal() == 95.0 and _shelf(pid, sid) == 7  # sin doble cargo/reserva
        assert _n_requests() == 1 and _n_deliveries() == 1

    def test_different_keys_create_separate_sends(self):
        sid = _mk_store(); pid = _mk_product(sid, 10)
        requests.post(f"{API}/company/deliveries", headers=_hdr(),
                      json=_body(str(uuid.uuid4()), sid, pid, 2))
        requests.post(f"{API}/company/deliveries", headers=_hdr(),
                      json=_body(str(uuid.uuid4()), sid, pid, 2))
        assert _n_requests() == 2 and _n_deliveries() == 2
        assert _bal() == 90.0 and _shelf(pid, sid) == 6

    def test_insufficient_balance_leaves_no_trace(self):
        _seed(balance=3.0)  # fee 5 > saldo
        sid = _mk_store(); pid = _mk_product(sid, 10)
        r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                          json=_body(str(uuid.uuid4()), sid, pid, 2))
        assert r.status_code == 402, r.text
        assert _bal() == 3.0                 # sin cargo
        assert _n_requests() == 0            # intención eliminada
        assert _n_deliveries() == 0
        assert _shelf(pid, sid) == 10        # sin reserva

    def test_insufficient_stock_refunds_and_leaves_no_trace(self):
        sid = _mk_store(); pid = _mk_product(sid, 1)   # solo 1 en tienda
        r = requests.post(f"{API}/company/deliveries", headers=_hdr(),
                          json=_body(str(uuid.uuid4()), sid, pid, 5))
        assert r.status_code == 409, r.text
        assert _bal() == 100.0               # tarifa reembolsada
        assert _n_requests() == 0 and _n_deliveries() == 0
        assert _shelf(pid, sid) == 1         # intacto
