"""iter268 — Dashboard por moneda + desglose por cliente del pasivo.

Verifica el endpoint GET /admin/company-funds/client-balances/{currency}:
1. Devuelve a quién se le debe y cuánto (vip_balances por moneda), ordenado
   de mayor a menor, con total consistente.
2. USD fusiona el campo legado vip_balance_usd.
3. Los admins/empleados no aparecen como clientes; sin permiso → 403.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
CCY = "I268X"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _get(currency, tok=ADMIN_TOKEN):
    return requests.get(
        f"{API}/admin/company-funds/client-balances/{currency}",
        headers=_hdr(tok))


def test_breakdown_lists_clients_sorted_with_total():
    db = _db()
    uid_extra = f"u_{CCY}_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid_extra, "role": "client", "name": "Cliente 268",
        "email": f"{uid_extra}@test.com",
        "vip_balances": {CCY: 20.0}})
    db.users.update_one({"user_id": "user_test_vip01"},
                        {"$set": {f"vip_balances.{CCY}": 30.0}})
    try:
        r = _get(CCY)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["currency"] == CCY
        assert data["total"] == 50.0, data
        rows = data["clients"]
        assert [c["amount"] for c in rows] == [30.0, 20.0], \
            "ordenado de mayor a menor deuda"
        assert rows[0]["user_id"] == "user_test_vip01"
        assert rows[1]["name"] == "Cliente 268"
        assert all(c.get("email") for c in rows), "cada fila identifica al cliente"
    finally:
        db.users.delete_one({"user_id": uid_extra})
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$unset": {f"vip_balances.{CCY}": ""}})


def test_usd_merges_legacy_field_and_staff_excluded():
    db = _db()
    uid = f"u_{CCY}_{uuid.uuid4().hex[:8]}"
    staff = f"u_{CCY}_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid, "role": "client", "name": "Legacy USD",
        "email": f"{uid}@test.com",
        "vip_balances": {"USD": 10.0}, "vip_balance_usd": 5.0})
    db.users.insert_one({
        "user_id": staff, "role": "employee", "name": "Empleado",
        "email": f"{staff}@test.com", "vip_balances": {"USD": 999.0}})
    try:
        r = _get("USD")
        assert r.status_code == 200, r.text
        rows = {c["user_id"]: c for c in r.json()["clients"]}
        assert rows[uid]["amount"] == 15.0, \
            "USD debe fusionar vip_balances.USD + vip_balance_usd"
        assert staff not in rows, "el staff no es un cliente acreedor"
    finally:
        db.users.delete_many({"user_id": {"$in": [uid, staff]}})


def test_requires_company_funds_permission():
    r = requests.get(f"{API}/admin/company-funds/client-balances/USD")
    assert r.status_code in (401, 403), r.status_code
