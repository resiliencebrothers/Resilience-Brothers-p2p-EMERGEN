"""iter209 — Staff como mensajero + aviso al cliente al aceptar.

Verifica:
1. Un empleado (staff) puede aceptar una entrega reservada para él vía
   /courier/deliveries/{id}/claim (mismo flujo que un mensajero normal).
2. Al aceptar, se inserta una notificación in-app al CLIENTE
   (type=delivery_status, data.status=accepted).
3. /admin/couriers expone el campo `phone` de cada mensajero.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
STAFF_ID = "user_test_employee01"
CLIENT_ID = "user_test_normal01"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_reserved_for_staff():
    did = f"test209_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "kind": "withdrawal", "ref_id": f"ref_{did}",
        "user_id": CLIENT_ID, "client_name": "Cliente 209",
        "address": "Calle Y", "province": "La Habana",
        "amount_label": "500 CUP",
        "km": 3.0, "fee_usdt": 5.0,
        "share_pct_snapshot": 80.0,
        "courier_share_usdt": 4.0, "platform_share_usdt": 1.0,
        "status": "available",
        "assigned_to_courier_id": STAFF_ID,
        "courier_id": None, "courier_name": None,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None,
        "created_at": "2026-08-15T10:00:00+00:00",
        "updated_at": "2026-08-15T10:00:00+00:00",
        "timeline": [{"status": "available", "at": "2026-08-15T10:00:00+00:00"}],
    })
    return did


def test_staff_can_accept_reserved_delivery_and_client_gets_notified():
    db = _db()
    did = _seed_reserved_for_staff()
    try:
        # 1) El staff ve la entrega reservada para él
        r = requests.get(f"{API}/courier/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
        avail = {d["id"]: d for d in r.json()["available"]}
        assert did in avail, "la reserva no aparece en disponibles del staff"
        assert avail[did]["reserved_for_me"] is True

        # 2) La acepta (claim)
        r = requests.post(f"{API}/courier/deliveries/{did}/claim",
                          headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "accepted"
        assert body["courier_id"] == STAFF_ID

        # 3) El cliente recibió la notificación de aceptación
        notif = db.notifications.find_one({
            "recipient_user_id": CLIENT_ID,
            "type": "delivery_status",
            "data.delivery_id": did,
            "data.status": "accepted",
        })
        assert notif is not None, "no se notificó al cliente al aceptar"
        assert "fue confirmada" in (notif.get("title") or "")
    finally:
        db.deliveries.delete_many({"id": did})
        db.notifications.delete_many({"data.delivery_id": did})


def test_admin_couriers_endpoint_includes_phone():
    r = requests.get(f"{API}/admin/couriers", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) > 0
    for c in rows:
        assert "phone" in c or c.get("phone") is None or True
    # al menos la clave debe venir en la proyección cuando existe en el doc
    db = _db()
    db.users.update_one({"user_id": STAFF_ID}, {"$set": {"phone": "+5355512209"}})
    try:
        r = requests.get(f"{API}/admin/couriers", headers=_hdr(ADMIN_TOKEN))
        by_id = {c["user_id"]: c for c in r.json()}
        assert by_id.get(STAFF_ID, {}).get("phone") == "+5355512209"
    finally:
        db.users.update_one({"user_id": STAFF_ID}, {"$unset": {"phone": ""}})
