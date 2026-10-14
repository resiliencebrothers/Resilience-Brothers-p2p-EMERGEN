"""A08 / ABA — un ACEPTAR o RECHAZAR atrasado de un ciclo de asignación
anterior NO debe modificar una reserva posterior, ni siquiera cuando la entrega
vuelve al MISMO mensajero en un ciclo nuevo (A -> B -> A).

Cada asignación lleva un `assignment_uid` propio (estable en reintentos de la
misma asignación, nuevo en cada ciclo distinto). Aceptar y rechazar se atan a
esa identidad: una petición con el uid viejo pierde con 409 y deja intacta la
reserva nueva. Se mantiene compatible la toma de trabajos realmente libres y las
reservas heredadas sin uid.
"""
import os
import uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
A_ID = "user_test_vip01"        # mensajero A (is_courier)
B_ID = "user_test_employee01"   # mensajero B (role employee → mensajero)
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
    did = f"men11_{uuid.uuid4().hex[:10]}"
    db.deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": "MEN11", "address": "Calle 1",
        "amount_label": "100 USDT", "km": 2, "fee_usdt": 5,
        "courier_share_usdt": 4, "platform_share_usdt": 1,
        "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    return did


def _assign(did, courier_id):
    return requests.post(f"{API}/admin/deliveries/{did}/assign",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"courier_id": courier_id}, timeout=15)


def _reject(did, tok, uid, reason="No puedo ahora mismo"):
    body = {"reason": reason}
    if uid is not None:
        body["assignment_uid"] = uid
    return requests.post(f"{API}/courier/deliveries/{did}/reject-reservation",
                         headers=_hdr(tok), json=body, timeout=15)


def _claim(did, tok, uid=None):
    body = {} if uid is None else {"assignment_uid": uid}
    return requests.post(f"{API}/courier/deliveries/{did}/claim",
                         headers=_hdr(tok), json=body, timeout=15)


def _uid(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0}).get(
        "assignment_uid")


def _doc(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})


def test_stale_reject_does_not_wipe_new_assignment_ABA():
    """A -> B -> A: el rechazo atrasado de A (uid viejo) no borra la reserva
    nueva de A (uid nuevo)."""
    did = _mk_free()
    try:
        assert _assign(did, A_ID).status_code == 200
        uid1 = _uid(did)
        assert uid1
        # A rechaza con uid1 → libera (y el uid desaparece)
        assert _reject(did, VIP_TOKEN, uid1).status_code == 200
        assert _uid(did) is None
        # admin asigna a B → uid2
        assert _assign(did, B_ID).status_code == 200
        uid2 = _uid(did)
        assert uid2 and uid2 != uid1
        # B rechaza → libera
        assert _reject(did, B_TOKEN, uid2).status_code == 200
        # admin asigna a A otra vez → uid3 (CICLO NUEVO)
        assert _assign(did, A_ID).status_code == 200
        uid3 = _uid(did)
        assert uid3 and uid3 != uid1
        # se REANUDA el rechazo viejo de A con uid1 → 409 y NO borra la reserva
        r = _reject(did, VIP_TOKEN, uid1)
        assert r.status_code == 409, r.text
        d = _doc(did)
        assert d["status"] == "available"
        assert d["assigned_to_courier_id"] == A_ID
        assert d.get("assignment_uid") == uid3  # reserva nueva intacta
    finally:
        _cleanup(did)


def test_stale_claim_does_not_accept_new_assignment_ABA():
    """A -> A (ciclo nuevo): un ACEPTAR atrasado con uid viejo pierde con 409 y
    no acepta la reserva nueva; con el uid vigente sí acepta."""
    did = _mk_free()
    try:
        assert _assign(did, A_ID).status_code == 200
        uid1 = _uid(did)
        assert _reject(did, VIP_TOKEN, uid1).status_code == 200
        assert _assign(did, A_ID).status_code == 200
        uid3 = _uid(did)
        assert uid3 != uid1
        # aceptar ATRASADO con uid1 → 409, sigue available/reservada a A
        r = _claim(did, VIP_TOKEN, uid1)
        assert r.status_code == 409, r.text
        d = _doc(did)
        assert d["status"] == "available"
        assert d["assigned_to_courier_id"] == A_ID
        assert d.get("assignment_uid") == uid3
        # aceptar con el uid VIGENTE → ok
        r = _claim(did, VIP_TOKEN, uid3)
        assert r.status_code == 200, r.text
        d = _doc(did)
        assert d["status"] == "accepted"
        assert d["courier_id"] == A_ID
        assert d.get("assignment_uid") == uid3  # el ciclo se CONSERVA al aceptar
    finally:
        _cleanup(did)


def test_reassign_to_same_courier_keeps_uid_stable_on_retry():
    """Reintento de la MISMA asignación (A -> A sin ciclo intermedio): el uid se
    mantiene estable para no invalidar la vista del mensajero."""
    did = _mk_free()
    try:
        assert _assign(did, A_ID).status_code == 200
        uid1 = _uid(did)
        assert _assign(did, A_ID).status_code == 200  # reintento idempotente
        assert _uid(did) == uid1
    finally:
        _cleanup(did)


def test_free_take_without_uid_still_works():
    """Toma de un trabajo realmente libre: sin uid, el claim funciona."""
    did = _mk_free()
    try:
        r = _claim(did, VIP_TOKEN, None)
        assert r.status_code == 200, r.text
        d = _doc(did)
        assert d["status"] == "accepted" and d["courier_id"] == A_ID
    finally:
        _cleanup(did)


def test_legacy_reservation_without_uid_can_be_rejected():
    """Reserva heredada SIN assignment_uid: el rechazo sin uid la libera."""
    did = _mk_free()
    try:
        _db().deliveries.update_one({"id": did}, {"$set": {
            "assigned_to_courier_id": A_ID,
            "assigned_to_courier_name": "VIP Test"}})
        r = _reject(did, VIP_TOKEN, None)
        assert r.status_code == 200, r.text
        assert _doc(did)["assigned_to_courier_id"] is None
    finally:
        _cleanup(did)


def test_claim_blocked_during_origin_cancel_intent_M01():
    """M01 — un ACEPTAR que llega mientras el cliente cancela su operación de
    origen (`origin_cancel_intent`) pierde con 409; no toma algo que se anula.
    El sello 'delivered' ya estaba protegido, la aceptación también debe serlo.
    """
    did = _mk_free()
    try:
        _db().deliveries.update_one({"id": did}, {"$set": {
            "assigned_to_courier_id": A_ID,
            "assignment_uid": "uidcancel123",
            "origin_cancel_intent": {"at": _now(), "by": "client",
                                     "token": "t1"}}})
        r = _claim(did, VIP_TOKEN, "uidcancel123")
        assert r.status_code == 409, r.text
        assert "cancel" in r.json().get("detail", "").lower()
        assert _doc(did)["status"] == "available"  # no aceptada
    finally:
        _cleanup(did)
