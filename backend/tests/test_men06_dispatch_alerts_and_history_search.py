"""MEN-06 — (1) las alertas de reserva lenta / entrega detenida llegan también
a los empleados autorizados a despachar (no solo admins); (2) buscador del
Historial por cliente / mensajero / fecha.
"""
import os
import uuid
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
ADMIN_ID = "user_test_admin01"
EMP_ID = "user_test_employee01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _old(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        loop.close()


def _set_emp_perms(perms):
    if perms is None:
        _db().users.update_one({"user_id": EMP_ID},
                               {"$unset": {"allowed_permissions": ""}})
    else:
        _db().users.update_one({"user_id": EMP_ID},
                               {"$set": {"allowed_permissions": perms}})


def _plant_stale_reservation():
    did = f"men06_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": "MEN06 Lenta",
        "amount_label": "100 USDT", "address": "Calle 1", "province": "La Habana",
        "km": 2, "fee_usdt": 5, "courier_share_usdt": 4, "platform_share_usdt": 1,
        "assigned_to_courier_id": VIP_ID, "assigned_to_courier_name": "VIP",
        "courier_id": None, "courier_name": None,
        "created_at": _old(1000), "updated_at": _old(1000),
    })
    return did


def _run_alerts():
    async def _f():
        from services.deliveries import alert_attention_items
        return await alert_attention_items()
    return _run(_f)


def _stale_recipients(did):
    cur = _db().notifications.find(
        {"type": "delivery_stale", "data.delivery_id": did})
    return {n["recipient_user_id"] for n in cur}


def test_dispatch_alert_reaches_authorized_employee_and_admin():
    _set_emp_perms(["deliveries", "deliveries_assign"])
    did = _plant_stale_reservation()
    try:
        _run_alerts()
        recips = _stale_recipients(did)
        assert ADMIN_ID in recips          # in-app para el admin
        assert EMP_ID in recips            # empleado AUTORIZADO (tarea)
    finally:
        _db().deliveries.delete_one({"id": did})
        _db().notifications.delete_many({"data.delivery_id": did})
        _set_emp_perms(None)


def test_dispatch_alert_excludes_unauthorized_employee():
    _set_emp_perms(["deliveries"])          # sin deliveries_assign
    did = _plant_stale_reservation()
    try:
        _run_alerts()
        recips = _stale_recipients(did)
        assert ADMIN_ID in recips
        assert EMP_ID not in recips
    finally:
        _db().deliveries.delete_one({"id": did})
        _db().notifications.delete_many({"data.delivery_id": did})
        _set_emp_perms(None)


# ------------------------------------------------------------------
# Buscador del Historial
# ------------------------------------------------------------------

def _mk_history(client_name, courier_name, created_at=None):
    did = f"men06s_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "status": "confirmed", "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": client_name,
        "courier_name": courier_name, "courier_id": VIP_ID,
        "amount_label": "100 USDT", "address": "Calle 1",
        "km": 2, "fee_usdt": 5, "courier_share_usdt": 4, "platform_share_usdt": 1,
        "created_at": created_at or _now(), "updated_at": created_at or _now(),
    })
    return did


def _search(term):
    r = requests.get(f"{API}/admin/deliveries", headers=_hdr(),
                     params={"status": "history", "search": term}, timeout=15)
    assert r.status_code == 200, r.text
    return {d["id"] for d in r.json()}


def test_history_search_by_client_courier_and_date():
    tagc = uuid.uuid4().hex[:8]
    tagk = uuid.uuid4().hex[:8]
    hit_client = _mk_history(f"Cliente {tagc}", "Mensajero Pepe")
    hit_courier = _mk_history("Cliente Normal", f"Mensajero {tagk}")
    dated = _mk_history("Cliente Fecha", "Mensajero X",
                        created_at="2024-03-15T10:00:00+00:00")
    try:
        # por cliente
        assert hit_client in _search(tagc)
        assert hit_courier not in _search(tagc)
        # por mensajero
        assert hit_courier in _search(tagk)
        assert hit_client not in _search(tagk)
        # por fecha (prefijo YYYY-MM-DD)
        assert dated in _search("2024-03-15")
    finally:
        _db().deliveries.delete_many(
            {"id": {"$in": [hit_client, hit_courier, dated]}})
