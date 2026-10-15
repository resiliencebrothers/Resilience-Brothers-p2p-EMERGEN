"""Auditoría de filtros Mongo (MEN23) — endpoints admin/mensajería que llevan
identificadores del body a filtros deben rechazar NO-escalares (objetos, arrays,
números, booleanos) para impedir inyección de operadores de consulta.

Cubre:
- POST /admin/deliveries (admin_create_delivery) → ref_id
- POST /admin/deliveries/{id}/assign (admin_assign_delivery) → courier_id
- POST /courier/deliveries/{id}/reject-reservation → assignment_uid
"""
import os
import uuid as _uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_admin_create_delivery_rejects_operator_ref_id():
    # ref_id como objeto {"$ne": null} NO debe interpretarse como operador.
    r = requests.post(f"{API}/admin/deliveries", headers=_hdr(),
                      json={"kind": "withdrawal", "ref_id": {"$ne": None}})
    assert r.status_code == 400, r.text
    assert "ref_id" in (r.json().get("detail") or "").lower()


def test_admin_create_delivery_rejects_array_ref_id():
    r = requests.post(f"{API}/admin/deliveries", headers=_hdr(),
                      json={"kind": "redemption", "ref_id": ["x"]})
    assert r.status_code == 400, r.text


def test_admin_assign_rejects_operator_courier_id():
    # Prepara una entrega real disponible.
    did = f"audit_{_uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "client_name": "AUDIT", "created_at": _now(), "updated_at": _now()})
    try:
        r = requests.post(f"{API}/admin/deliveries/{did}/assign", headers=_hdr(),
                          json={"courier_id": {"$ne": None}})
        assert r.status_code == 400, r.text
        assert "courier_id" in (r.json().get("detail") or "").lower()
        # La entrega NO fue asignada.
        d = _db().deliveries.find_one({"id": did}, {"_id": 0})
        assert d.get("assigned_to_courier_id") in (None, "", False) or \
            "assigned_to_courier_id" not in d
    finally:
        _db().deliveries.delete_many({"id": did})


def test_reject_reservation_rejects_operator_assignment_uid():
    # Endpoint de mensajero: assignment_uid como objeto → 400 (requiere token
    # de un mensajero; admin es staff con is_courier/role válido en el seed).
    did = f"audit_{_uuid.uuid4().hex[:10]}"
    # Reservada al "mensajero" admin del seed para que pase el guard de propiedad.
    admin_uid = _db().user_sessions.find_one(
        {"session_token": "test_session_admin_X"}, {"_id": 0, "user_id": 1})
    assert admin_uid, "sesión admin no sembrada"
    _db().deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "client_name": "AUDIT", "assigned_to_courier_id": admin_uid["user_id"],
        "assignment_uid": "U1", "created_at": _now(), "updated_at": _now()})
    try:
        r = requests.post(f"{API}/courier/deliveries/{did}/reject-reservation",
                          headers=_hdr(),
                          json={"assignment_uid": {"$ne": None},
                                "reason": "motivo de prueba válido"})
        assert r.status_code == 400, r.text
        assert "assignment_uid" in (r.json().get("detail") or "").lower()
    finally:
        _db().deliveries.delete_many({"id": did})
