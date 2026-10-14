"""MEN-19 — Acción Rápida Reserva + Filtro por Reasignadas.

Acción Rápida: el admin puede reasignar directamente una RESERVA lenta aún no
aceptada (`override_reservation`) a otro mensajero, con CAS por `expected_uid`
para que una aceptación del mensajero anterior en paralelo pierda con 409. La
reasignación queda AUDITADA (`reassign_audit`, stage=reservation), y por tanto
aparece en el filtro "Solo reasignadas" del Historial.
"""
import os
import uuid as _uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
A_ID = "user_test_vip01"        # mensajero A (reservado inicialmente)
B_ID = "user_test_employee01"   # mensajero B (destino de la reasignación)


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_reservation(uid="uidA"):
    """Reserva lenta: available + reservada a A, con ciclo `uid`."""
    db = _db()
    db.users.update_one({"user_id": A_ID}, {"$set": {"is_courier": True}})
    did = f"men19_{_uuid.uuid4().hex[:10]}"
    db.deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "client_name": "MEN19", "amount_label": "300 USDT", "km": 2,
        "fee_usdt": 5, "courier_share_usdt": 4, "platform_share_usdt": 1,
        "assigned_to_courier_id": A_ID, "assigned_to_courier_name": "VIP Test",
        "assignment_uid": uid, "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    return did


def _assign(did, courier_id=None, expected_uid=None, override=False):
    body = {}
    if courier_id:
        body["courier_id"] = courier_id
    if expected_uid is not None:
        body["expected_uid"] = expected_uid
    if override:
        body["override_reservation"] = True
    return requests.post(f"{API}/admin/deliveries/{did}/assign",
                         headers=_hdr(ADMIN_TOKEN), json=body, timeout=15)


def _doc(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})


# ---------------------------------------------------------------------------

def test_quick_reassign_reservation_overrides_and_audits():
    did = _mk_reservation(uid="uidA1")
    try:
        r = _assign(did, B_ID, expected_uid="uidA1", override=True)
        assert r.status_code == 200, r.text
        d = _doc(did)
        assert d["status"] == "available"
        assert d["assigned_to_courier_id"] == B_ID       # re-reservada a B
        assert d["assignment_uid"] and d["assignment_uid"] != "uidA1"  # ciclo nuevo
        aud = d.get("reassign_audit")
        assert aud and aud["mode"] == "reassigned"
        assert aud["stage"] == "reservation"
        assert aud["from_courier_id"] == A_ID
        assert aud["to_courier_id"] == B_ID
    finally:
        _cleanup(did)


def test_reassign_reservation_without_override_is_blocked():
    did = _mk_reservation(uid="uidA2")
    try:
        r = _assign(did, B_ID, expected_uid="uidA2", override=False)
        assert r.status_code == 409, r.text
        assert _doc(did)["assigned_to_courier_id"] == A_ID  # intacta
    finally:
        _cleanup(did)


def test_stale_override_loses_with_409():
    did = _mk_reservation(uid="uidA3")
    try:
        # El admin creyó ver un ciclo que ya no es el vigente → pierde con 409.
        r = _assign(did, B_ID, expected_uid="uidWRONG", override=True)
        assert r.status_code == 409, r.text
        assert _doc(did)["assigned_to_courier_id"] == A_ID
        assert _doc(did)["assignment_uid"] == "uidA3"
    finally:
        _cleanup(did)


def test_reassigned_only_filter_returns_only_audited():
    did = _mk_reservation(uid="uidA4")
    try:
        assert _assign(did, B_ID, expected_uid="uidA4", override=True).status_code == 200
        r = requests.get(f"{API}/admin/deliveries",
                         headers=_hdr(ADMIN_TOKEN),
                         params={"reassigned_only": "true", "limit": 200},
                         timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        ids = {x["id"] for x in rows}
        assert did in ids
        assert all(x.get("reassign_audit") for x in rows)
    finally:
        _cleanup(did)
