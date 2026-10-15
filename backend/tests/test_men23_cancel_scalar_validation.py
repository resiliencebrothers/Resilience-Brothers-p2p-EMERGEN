"""MEN23 — el endpoint de cancelación admin exige ESCALARES: rechaza objetos,
arrays, números y booleanos en expected_status / expected_uid / note antes de
construir el filtro Mongo. Un operador en lugar del identificador podría
interpretarse como operador de consulta y romper la igualdad de ciclo/estado.
"""
import os
import uuid as _uuid
from datetime import datetime, timezone

import requests
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


def _mk(uid="U1"):
    did = f"men23_{_uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "status": "available", "kind": "withdrawal",
        "client_name": "MEN23", "amount_label": "100 USDT",
        "assigned_to_courier_id": A_ID, "assignment_uid": uid,
        "courier_id": None, "created_at": _now(), "updated_at": _now()})
    return did


def _cancel(did, body):
    return requests.post(f"{API}/admin/deliveries/{did}/cancel",
                         headers=_hdr(ADMIN_TOKEN), json=body, timeout=15)


def _doc(did):
    return _db().deliveries.find_one({"id": did}, {"_id": 0})


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})


def test_expected_uid_operator_object_rejected():
    did = _mk("U1")
    try:
        # UID enviado como OBJETO de condición → 400, y la entrega NO se cancela.
        r = _cancel(did, {"expected_status": "available",
                          "expected_uid": {"$ne": None}})
        assert r.status_code == 400, r.text
        assert _doc(did)["status"] == "available"
    finally:
        _cleanup(did)


def test_expected_status_operator_object_rejected():
    did = _mk("U1")
    try:
        # Estado enviado como objeto {"$ne": "confirmed"} → 400, sin cambios.
        r = _cancel(did, {"expected_status": {"$ne": "confirmed"},
                          "expected_uid": "U1"})
        assert r.status_code == 400, r.text
        assert _doc(did)["status"] == "available"
    finally:
        _cleanup(did)


def test_expected_uid_array_and_number_rejected():
    did = _mk("U1")
    try:
        for bad in [["U1"], 123, True]:
            r = _cancel(did, {"expected_status": "available", "expected_uid": bad})
            assert r.status_code == 400, f"{bad!r} -> {r.status_code} {r.text}"
        assert _doc(did)["status"] == "available"
    finally:
        _cleanup(did)


def test_unknown_status_string_rejected():
    did = _mk("U1")
    try:
        # Cadena pero fuera del vocabulario permitido → 400.
        r = _cancel(did, {"expected_status": "banana", "expected_uid": "U1"})
        assert r.status_code == 400, r.text
        assert _doc(did)["status"] == "available"
    finally:
        _cleanup(did)


def test_note_non_string_rejected():
    did = _mk("U1")
    try:
        r = _cancel(did, {"expected_status": "available", "expected_uid": "U1",
                          "note": {"$ne": ""}})
        assert r.status_code == 400, r.text
        assert _doc(did)["status"] == "available"
    finally:
        _cleanup(did)


def test_valid_scalar_cancel_still_works():
    did = _mk("U1")
    try:
        r = _cancel(did, {"expected_status": "available", "expected_uid": "U1",
                          "note": "ok"})
        assert r.status_code == 200, r.text
        assert _doc(did)["status"] == "cancelled"
    finally:
        _cleanup(did)
