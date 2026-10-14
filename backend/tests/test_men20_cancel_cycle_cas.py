"""OP01 — la cancelación admin se liga al ESTADO y CICLO observados.

Cancelar desde una tarjeta ANTIGUA no debe anular otro ciclo (reserva ya
reasignada a otro mensajero) ni un trabajo ya aceptado. La escritura de
cancelación condiciona atómicamente a `expected_status` + `expected_uid`;
ante un cambio responde 409 sin cancelar. La cancelación legítima (vista
vigente) sigue funcionando, y la ausencia de ciclo (dato heredado/libre) no
autoriza a anular un ciclo nuevo.
"""
import os
import uuid as _uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
A_ID = "user_test_vip01"        # mensajero A (reservado / acepta)
A_TOKEN = VIP_TOKEN
B_ID = "user_test_employee01"   # mensajero B (destino de reasignación)


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_reservation(uid):
    db = _db()
    db.users.update_one({"user_id": A_ID}, {"$set": {"is_courier": True}})
    did = f"op01_{_uuid.uuid4().hex[:10]}"
    db.deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "client_name": "OP01", "amount_label": "300 USDT", "km": 2,
        "fee_usdt": 5, "courier_share_usdt": 4, "platform_share_usdt": 1,
        "assigned_to_courier_id": A_ID, "assigned_to_courier_name": "VIP Test",
        "assignment_uid": uid, "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    return did


def _cancel(did, expected_status=None, expected_uid="__omit__"):
    body = {}
    if expected_status is not None:
        body["expected_status"] = expected_status
    if expected_uid != "__omit__":
        body["expected_uid"] = expected_uid
    return requests.post(f"{API}/admin/deliveries/{did}/cancel",
                         headers=_hdr(ADMIN_TOKEN), json=body, timeout=15)


def _override_assign(did, courier_id, expected_uid):
    return requests.post(f"{API}/admin/deliveries/{did}/assign",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"courier_id": courier_id,
                               "expected_uid": expected_uid,
                               "override_reservation": True}, timeout=15)


def _claim(did, uid, tok):
    return requests.post(f"{API}/courier/deliveries/{did}/claim",
                         headers=_hdr(tok), json={"assignment_uid": uid},
                         timeout=15)


def _doc(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})


# ---------------------------------------------------------------------------

def test_stale_cancel_after_reassign_is_blocked():
    did = _mk_reservation("U1")
    try:
        assert _override_assign(did, B_ID, "U1").status_code == 200
        d = _doc(did)
        assert d["assigned_to_courier_id"] == B_ID and d["assignment_uid"] != "U1"
        # Operador cancela desde la tarjeta ANTIGUA (A/U1): debe perder con 409.
        r = _cancel(did, expected_status="available", expected_uid="U1")
        assert r.status_code == 409, r.text
        d2 = _doc(did)
        assert d2["status"] == "available"            # NO cancelada
        assert d2["assigned_to_courier_id"] == B_ID    # ciclo de B intacto
    finally:
        _cleanup(did)


def test_cancel_after_acceptance_is_blocked():
    did = _mk_reservation("U1")
    try:
        assert _claim(did, "U1", A_TOKEN).status_code == 200
        assert _doc(did)["status"] == "accepted"
        # La tarjeta mostraba una RESERVA (available); ya fue aceptada → 409.
        r = _cancel(did, expected_status="available", expected_uid="U1")
        assert r.status_code == 409, r.text
        assert _doc(did)["status"] == "accepted"       # NO cancelada
    finally:
        _cleanup(did)


def test_valid_cancel_when_view_is_current():
    did = _mk_reservation("U1")
    try:
        r = _cancel(did, expected_status="available", expected_uid="U1")
        assert r.status_code == 200, r.text
        assert _doc(did)["status"] == "cancelled"
    finally:
        _cleanup(did)


def test_legacy_without_uid_cancels_only_if_still_without_uid():
    db = _db()
    did = f"op01_legacy_{_uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "client_name": "OP01 legacy", "amount_label": "50 USDT",
        "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    })
    try:
        # Entrega libre sin ciclo: cancelación con expected_uid=null es válida.
        r = _cancel(did, expected_status="available", expected_uid=None)
        assert r.status_code == 200, r.text
        assert _doc(did)["status"] == "cancelled"
    finally:
        _cleanup(did)


def test_absence_of_uid_does_not_cancel_a_new_cycle():
    did = _mk_reservation("U9")  # esta SÍ tiene ciclo
    try:
        # El operador creyó ver una entrega sin ciclo (expected_uid=null); como
        # el documento ahora tiene ciclo, NO debe cancelarse.
        r = _cancel(did, expected_status="available", expected_uid=None)
        assert r.status_code == 409, r.text
        assert _doc(did)["status"] == "available"
    finally:
        _cleanup(did)


def test_payout_protection_preserved():
    db = _db()
    did = f"op01_payout_{_uuid.uuid4().hex[:8]}"
    db.deliveries.insert_one({
        "id": did, "status": "delivered", "kind": "withdrawal",
        "client_name": "OP01 payout", "amount_label": "90 USDT",
        "courier_id": A_ID, "courier_name": "VIP Test",
        "assignment_uid": "UP1", "payout_credited": True,
        "created_at": _now(), "updated_at": _now(),
    })
    try:
        # Aunque el estado y el ciclo coincidan, la comisión ya acreditada
        # impide cancelar.
        r = _cancel(did, expected_status="delivered", expected_uid="UP1")
        assert r.status_code == 409, r.text
        assert _doc(did)["status"] == "delivered"
    finally:
        _cleanup(did)


# ---------------------------------------------------------------------------
# MEN22 — el endpoint EXIGE declarar lo observado; omitir los campos es 400.
# Cierra el hueco por el que un cliente podía saltarse el CAS por omisión.

def test_cancel_requires_expected_status():
    did = _mk_reservation("U1")
    try:
        r = _cancel(did, expected_status=None, expected_uid="U1")  # falta status
        assert r.status_code == 400, r.text
        assert _doc(did)["status"] == "available"  # no se tocó
    finally:
        _cleanup(did)


def test_cancel_requires_expected_uid_key():
    did = _mk_reservation("U1")
    try:
        # La clave expected_uid está AUSENTE (distinto de null) → 400.
        r = _cancel(did, expected_status="available", expected_uid="__omit__")
        assert r.status_code == 400, r.text
        assert _doc(did)["status"] == "available"  # no se tocó
    finally:
        _cleanup(did)
