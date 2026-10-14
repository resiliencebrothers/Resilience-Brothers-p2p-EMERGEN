"""MEN-21 — cancelar una reserva PENDIENTE avisa al mensajero reservado.

La notificación de cancelación debe dirigirse al mensajero del ciclo
efectivamente cancelado: el aceptado si lo había, o el RESERVADO
(`assigned_to_courier_id`) cuando aún no había aceptación. Campana (persistente)
+ push, emitidos SOLO tras ganar la escritura; una petición obsoleta (409) no
debe anunciar cancelación, y un reintento no duplica avisos.
"""
import os
import uuid as _uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
A_ID = "user_test_vip01"
B_ID = "user_test_employee01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_reservation(uid, courier=A_ID, accepted=False):
    db = _db()
    did = f"men21_{_uuid.uuid4().hex[:10]}"
    doc = {
        "id": did, "kind": "withdrawal", "client_name": "MEN21",
        "amount_label": "300 USDT", "assignment_uid": uid,
        "created_at": _now(), "updated_at": _now(),
    }
    if accepted:
        doc.update({"status": "accepted", "courier_id": courier,
                    "courier_name": "Courier", "assigned_to_courier_id": None})
    else:
        doc.update({"status": "available", "courier_id": None,
                    "assigned_to_courier_id": courier,
                    "assigned_to_courier_name": "Courier"})
    db.deliveries.insert_one(doc)
    return did


def _cancel(did, expected_status, expected_uid="__omit__"):
    body = {"expected_status": expected_status}
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


def _notif_count(uid_user, did):
    return _db().notifications.count_documents({
        "recipient_user_id": uid_user, "type": "delivery_cancelled",
        "data.delivery_id": did})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})
    _db().notifications.delete_many({"data.delivery_id": did})


# ---------------------------------------------------------------------------

def test_cancel_reservation_notifies_reserved_courier():
    did = _mk_reservation("U1", courier=A_ID, accepted=False)
    try:
        assert _cancel(did, "available", "U1").status_code == 200
        assert _db().deliveries.find_one({"id": did})["status"] == "cancelled"
        assert _notif_count(A_ID, did) == 1  # reservado (sin courier_id) avisado
    finally:
        _cleanup(did)


def test_cancel_accepted_notifies_accepted_courier():
    did = _mk_reservation("U1", courier=A_ID, accepted=True)
    try:
        assert _cancel(did, "accepted", "U1").status_code == 200
        assert _notif_count(A_ID, did) == 1
    finally:
        _cleanup(did)


def test_stale_cancel_does_not_announce_cancellation():
    did = _mk_reservation("U1", courier=A_ID, accepted=False)
    try:
        # Reasignada a B (nuevo ciclo); el cancel desde la tarjeta vieja pierde.
        assert _override_assign(did, B_ID, "U1").status_code == 200
        assert _cancel(did, "available", "U1").status_code == 409
        # Ni A ni B reciben aviso de cancelación (no se canceló nada).
        assert _notif_count(A_ID, did) == 0
        assert _notif_count(B_ID, did) == 0
    finally:
        _cleanup(did)


def test_retry_does_not_duplicate_notification():
    did = _mk_reservation("U1", courier=A_ID, accepted=False)
    try:
        assert _cancel(did, "available", "U1").status_code == 200
        # Reintento con la misma vista: ya está cancelada → 409, sin duplicar.
        assert _cancel(did, "available", "U1").status_code == 409
        assert _notif_count(A_ID, did) == 1
    finally:
        _cleanup(did)
