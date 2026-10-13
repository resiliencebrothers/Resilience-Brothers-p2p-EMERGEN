"""MEN-05 — el aviso de RECHAZO de reserva llega a admins Y a los empleados
AUTORIZADOS a despachar (deliveries_assign), leyendo la fuente real de permisos
(`allowed_permissions`), no el campo inexistente `permissions`.
"""
import os
import uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
ADMIN_ID = "user_test_admin01"
EMP_ID = "user_test_employee01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_reserved():
    _db().users.update_one({"user_id": VIP_ID}, {"$set": {"is_courier": True}})
    did = f"men05_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": "MEN05",
        "amount_label": "100 USDT", "address": "Calle 1",
        "km": 2, "fee_usdt": 5, "courier_share_usdt": 4, "platform_share_usdt": 1,
        "assigned_to_courier_id": VIP_ID, "assigned_to_courier_name": "VIP Test",
        "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    return did


def _reject(did):
    return requests.post(f"{API}/courier/deliveries/{did}/reject-reservation",
                         headers=_hdr(VIP_TOKEN),
                         json={"reason": "No puedo atenderla ahora"}, timeout=15)


def _recipients_for(did):
    cur = _db().notifications.find(
        {"type": "delivery_rejected", "data.delivery_id": did})
    return {n["recipient_user_id"] for n in cur}


def _set_emp_perms(perms):
    if perms is None:
        _db().users.update_one({"user_id": EMP_ID},
                               {"$unset": {"allowed_permissions": ""}})
    else:
        _db().users.update_one({"user_id": EMP_ID},
                               {"$set": {"allowed_permissions": perms}})


def test_authorized_employee_and_admin_notified_on_reject():
    _set_emp_perms(["deliveries", "deliveries_assign"])
    did = _mk_reserved()
    try:
        r = _reject(did)
        assert r.status_code == 200, r.text
        recips = _recipients_for(did)
        assert ADMIN_ID in recips          # el admin siempre
        assert EMP_ID in recips            # empleado AUTORIZADO (MEN-05)
    finally:
        _db().deliveries.delete_one({"id": did})
        _db().notifications.delete_many({"data.delivery_id": did})
        _set_emp_perms(None)


def test_employee_without_dispatch_permission_not_notified():
    # Solo "deliveries" (sin deliveries_assign) -> NO recibe el aviso.
    _set_emp_perms(["deliveries"])
    did = _mk_reserved()
    try:
        r = _reject(did)
        assert r.status_code == 200, r.text
        recips = _recipients_for(did)
        assert ADMIN_ID in recips
        assert EMP_ID not in recips
    finally:
        _db().deliveries.delete_one({"id": did})
        _db().notifications.delete_many({"data.delivery_id": did})
        _set_emp_perms(None)


def test_employee_empty_perms_not_notified():
    # MEN-01: lista vacía NO concede deliveries_assign -> excluido.
    _set_emp_perms([])
    did = _mk_reserved()
    try:
        r = _reject(did)
        assert r.status_code == 200, r.text
        recips = _recipients_for(did)
        assert ADMIN_ID in recips
        assert EMP_ID not in recips
    finally:
        _db().deliveries.delete_one({"id": did})
        _db().notifications.delete_many({"data.delivery_id": did})
        _set_emp_perms(None)
