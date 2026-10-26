"""Auditoría Staff (26-10-2026) — STAFF-04, STAFF-05, STAFF-07.

- STAFF-04: ejecutar como mensajero (/courier/*) exige is_courier; ser staff
  (admin/employee) ya NO basta.
- STAFF-05: una cuenta de staff suspendida/en revisión pierde el acceso de
  inmediato (403) aunque su sesión siga viva.
- STAFF-07: un empleado con 'user_functions' NO puede modificar funciones de
  una cuenta de staff NI sus propias funciones/alcance (auto-escalada).
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN,
    with_totp_employee,
)

API = f"{BASE_URL}/api"
EMP = "user_test_employee01"
ADMIN = "user_test_admin01"
NORMAL = "user_test_normal01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _set(uid, fields):
    _db().users.update_one({"user_id": uid}, {"$set": fields})


def _unset(uid, fields):
    _db().users.update_one({"user_id": uid}, {"$unset": {f: "" for f in fields}})


# ------------------------------------------------------------------
# STAFF-04 — /courier/* exige is_courier
# ------------------------------------------------------------------

def test_staff04_courier_requires_is_courier_flag():
    # Empleado SIN is_courier → 403 aunque tenga el permiso 'deliveries'.
    _set(EMP, {"is_courier": False, "allowed_permissions": ["deliveries"]})
    try:
        r = requests.get(f"{API}/courier/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        assert "mensajero" in r.text.lower()
        # Con la marca is_courier → pasa el gate de rol de mensajero.
        _set(EMP, {"is_courier": True})
        r = requests.get(f"{API}/courier/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
    finally:
        _set(EMP, {"is_courier": False})
        _unset(EMP, ["allowed_permissions"])


def test_staff04_admin_without_is_courier_blocked():
    # Un admin sin is_courier tampoco pasa /courier/* (solo mensajeros).
    _set(ADMIN, {"is_courier": False})
    r = requests.get(f"{API}/courier/deliveries", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 403, r.text


# ------------------------------------------------------------------
# STAFF-05 — staff suspendido pierde acceso de inmediato
# ------------------------------------------------------------------

def test_staff05_suspended_employee_denied():
    _set(EMP, {"allowed_permissions": ["deliveries"], "account_status": "blocked"})
    try:
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        assert "suspend" in r.text.lower() or "revisión" in r.text.lower()
        # under_review también bloquea a staff.
        _set(EMP, {"account_status": "under_review"})
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
        # Al volver a 'active' recupera el acceso (con su permiso).
        _set(EMP, {"account_status": "active"})
        r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
    finally:
        _unset(EMP, ["allowed_permissions"])
        _set(EMP, {"account_status": "active"})


# ------------------------------------------------------------------
# STAFF-07 — sin auto-escalada ni edición de otras cuentas de staff
# ------------------------------------------------------------------

def test_staff07_employee_cannot_edit_own_functions():
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    try:
        r = requests.put(f"{API}/admin/users/{EMP}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD", "EUR"]}))
        assert r.status_code == 403, r.text
        # El empleado ES staff: queda bloqueado por el guard de cuenta-staff
        # (que subsume la auto-edición). Lo importante: NO puede escalar.
        body = r.text.lower()
        assert "propias" in body or "staff" in body
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff07_employee_cannot_edit_staff_target():
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    try:
        # Objetivo = un admin → no puede tocar sus funciones.
        r = requests.put(f"{API}/admin/users/{ADMIN}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD"]}))
        assert r.status_code == 403, r.text
        assert "staff" in r.text.lower()
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff07_employee_can_edit_normal_user_scope():
    # Control: editar el alcance de un CLIENTE normal sí está permitido.
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    prev = (_db().users.find_one({"user_id": NORMAL}, {"allowed_currencies": 1, "_id": 0})
            or {}).get("allowed_currencies")
    try:
        r = requests.put(f"{API}/admin/users/{NORMAL}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD"]}))
        assert r.status_code == 200, r.text
    finally:
        _unset(EMP, ["allowed_permissions"])
        if prev is None:
            _unset(NORMAL, ["allowed_currencies"])
        else:
            _set(NORMAL, {"allowed_currencies": prev})


# ------------------------------------------------------------------
# STAFF-06 — el feed en vivo (SSE) exige cuenta de staff activa
# ------------------------------------------------------------------

def test_staff06_suspended_staff_cannot_open_live_stream():
    _set(EMP, {"account_status": "blocked"})
    try:
        r = requests.get(f"{API}/live/stream", headers=_hdr(EMPLOYEE_TOKEN),
                         stream=True, timeout=10)
        try:
            assert r.status_code == 403, r.text
            assert "suspend" in r.text.lower() or "revisión" in r.text.lower()
        finally:
            r.close()
    finally:
        _set(EMP, {"account_status": "active"})


def test_staff06_normal_user_live_stream_ok():
    # Un cliente normal (no staff) abre el feed sin problema.
    r = requests.get(f"{API}/live/stream", headers=_hdr(NORMAL_TOKEN),
                     stream=True, timeout=10)
    try:
        assert r.status_code == 200, r.text
    finally:
        r.close()
