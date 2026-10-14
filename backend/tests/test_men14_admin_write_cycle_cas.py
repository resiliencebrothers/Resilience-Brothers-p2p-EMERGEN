"""M01-A / M01-B — las ESCRITURAS ADMINISTRATIVAS se condicionan al CICLO
(`assignment_uid`) que la operación examinó (concurrencia optimista / CAS).

- M01-A (`admin_assign_delivery`): una asignación atrasada que leyó un uid viejo
  (U1) no debe reescribirlo sobre el ciclo nuevo (U3). La "barrera real entre
  lectura y escritura" se reproduce de forma determinista pasando `expected_uid`
  con el ciclo observado: si ya no coincide, la escritura pierde con 409.
- M01-B (`admin_reassign_delivery`): una reasignación atrasada no debe actuar
  sobre un ciclo ACEPTADO posterior solo porque la entrega vuelva a estar
  aceptada por el mismo mensajero. El `assignment_uid` se conserva al aceptar,
  así se distinguen ciclos aceptados.

Incluye controles positivos del reintento/operación válidos (cuando el ciclo
realmente no cambió).
"""
import os
import uuid as _uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
A_ID = "user_test_vip01"        # mensajero A
A_TOKEN = VIP_TOKEN
B_ID = "user_test_employee01"   # mensajero B (role employee)
B_TOKEN = EMPLOYEE_TOKEN


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_free():
    db = _db()
    db.users.update_one({"user_id": A_ID}, {"$set": {"is_courier": True}})
    did = f"men14_{_uuid.uuid4().hex[:10]}"
    db.deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "ref_id": _uuid.uuid4().hex, "client_name": "MEN14", "address": "C 1",
        "amount_label": "100 USDT", "km": 2, "fee_usdt": 5,
        "courier_share_usdt": 4, "platform_share_usdt": 1,
        "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    return did


def _assign(did, courier_id, expected_uid=None):
    body = {"courier_id": courier_id}
    if expected_uid is not None:
        body["expected_uid"] = expected_uid
    return requests.post(f"{API}/admin/deliveries/{did}/assign",
                         headers=_hdr(ADMIN_TOKEN), json=body, timeout=15)


def _reassign(did, courier_id=None, expected_uid=None, reason="cambio"):
    body = {"reason": reason}
    if courier_id:
        body["courier_id"] = courier_id
    if expected_uid is not None:
        body["expected_uid"] = expected_uid
    return requests.post(f"{API}/admin/deliveries/{did}/reassign",
                         headers=_hdr(ADMIN_TOKEN), json=body, timeout=15)


def _reject(did, tok, uid):
    return requests.post(f"{API}/courier/deliveries/{did}/reject-reservation",
                         headers=_hdr(tok),
                         json={"reason": "no puedo", "assignment_uid": uid},
                         timeout=15)


def _claim(did, tok, uid):
    return requests.post(f"{API}/courier/deliveries/{did}/claim",
                         headers=_hdr(tok), json={"assignment_uid": uid},
                         timeout=15)


def _uid(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0}).get(
        "assignment_uid")


def _doc(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})


# ---------------------------------------------------------------- M01-A -----

def test_M01A_stale_admin_assign_does_not_restore_old_cycle():
    did = _mk_free()
    try:
        assert _assign(did, A_ID).status_code == 200
        u1 = _uid(did)
        # avanza el ciclo: A rechaza U1 (libre) y se reasigna a A con U3
        assert _reject(did, A_TOKEN, u1).status_code == 200
        assert _assign(did, A_ID).status_code == 200
        u3 = _uid(did)
        assert u3 and u3 != u1
        # orden administrativa ATRASADA que observó U1 → pierde con 409
        r = _assign(did, A_ID, expected_uid=u1)
        assert r.status_code == 409, r.text
        assert _uid(did) == u3  # NO retrocede a U1
        # el rechazo viejo con U1 sigue siendo inválido
        assert _reject(did, A_TOKEN, u1).status_code == 409
        assert _doc(did)["assigned_to_courier_id"] == A_ID
        assert _uid(did) == u3
    finally:
        _cleanup(did)


def test_M01A_valid_retry_same_cycle_keeps_uid():
    """Control positivo: reintento al mismo mensajero sobre el ciclo vigente →
    idempotente, conserva el uid."""
    did = _mk_free()
    try:
        assert _assign(did, A_ID).status_code == 200
        u1 = _uid(did)
        r = _assign(did, A_ID, expected_uid=u1)
        assert r.status_code == 200, r.text
        assert _uid(did) == u1  # estable
    finally:
        _cleanup(did)


# ---------------------------------------------------------------- M01-B -----

def test_M01B_stale_reassign_does_not_touch_new_accepted_cycle():
    did = _mk_free()
    try:
        # A acepta el ciclo C1
        assert _assign(did, A_ID).status_code == 200
        c1 = _uid(did)
        assert _claim(did, A_TOKEN, c1).status_code == 200
        assert _doc(did)["status"] == "accepted"
        assert _uid(did) == c1  # el ciclo se conserva al aceptar
        # avanza: reasigna a B (C2), B acepta; reasigna a A (C3), A acepta
        assert _reassign(did, B_ID, expected_uid=c1).status_code == 200
        c2 = _uid(did)
        assert c2 and c2 != c1
        assert _claim(did, B_TOKEN, c2).status_code == 200
        assert _reassign(did, A_ID, expected_uid=c2).status_code == 200
        c3 = _uid(did)
        assert c3 and c3 not in (c1, c2)
        assert _claim(did, A_TOKEN, c3).status_code == 200
        assert _doc(did)["status"] == "accepted"
        # reasignación ATRASADA que observó C1 → 409; el ciclo aceptado de A
        # (C3) queda intacto
        r = _reassign(did, B_ID, expected_uid=c1)
        assert r.status_code == 409, r.text
        d = _doc(did)
        assert d["status"] == "accepted"
        assert d["courier_id"] == A_ID
        assert d.get("assignment_uid") == c3
    finally:
        _cleanup(did)


def test_M01B_valid_reassign_current_cycle_succeeds():
    """Control positivo: reasignar observando el ciclo aceptado vigente →
    libera/reserva correctamente."""
    did = _mk_free()
    try:
        assert _assign(did, A_ID).status_code == 200
        c1 = _uid(did)
        assert _claim(did, A_TOKEN, c1).status_code == 200
        r = _reassign(did, B_ID, expected_uid=c1)
        assert r.status_code == 200, r.text
        d = _doc(did)
        assert d["status"] == "available"
        assert d["assigned_to_courier_id"] == B_ID
        assert d.get("assignment_uid") not in (None, c1)
    finally:
        _cleanup(did)
