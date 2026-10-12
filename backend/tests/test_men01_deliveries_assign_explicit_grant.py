"""MEN-01 — El permiso `deliveries_assign` exige concesión EXPLÍCITA.

Antes de este fix, un empleado con `allowed_permissions=[]` (o sin el campo)
pasaba el default de compatibilidad "acceso total" y podía ASIGNAR/RESERVAR
repartos a mensajeros — justamente la escalada de privilegios que el informe
previo advertía. Separa "hacer entregas" (`deliveries`) de "asignar repartos"
(`deliveries_assign`).

Casos del informe:
- admin → permitido.
- empleado perms=["deliveries"] → bloqueado (403).
- empleado perms=["deliveries","deliveries_assign"] → permitido.
- empleado perms=[] → bloqueado (EL FIX).
- empleado SIN campo allowed_permissions → bloqueado (EL FIX).
- cliente / mensajero no-empleado → bloqueado (control).
- Compatibilidad: empleado perms=[] SIGUE pasando el resto de módulos.
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN,
)

API = f"{BASE_URL}/api"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _set_perms(user_id, perms):
    _sync_db().users.update_one(
        {"user_id": user_id}, {"$set": {"allowed_permissions": list(perms)}})


def _unset_perms(user_id):
    _sync_db().users.update_one(
        {"user_id": user_id}, {"$unset": {"allowed_permissions": ""}})


# ------------------------------------------------------------------
# 1. Predicado puro (sin HTTP)
# ------------------------------------------------------------------

def test_predicate_explicit_grant_for_deliveries_assign():
    from services.permissions import _has_permission, EXPLICIT_GRANT_CODES

    assert "deliveries_assign" in EXPLICIT_GRANT_CODES

    # admin → siempre.
    assert _has_permission({"role": "admin"}, "deliveries_assign") is True

    # empleado con el permiso explícito → sí.
    emp_grant = {"role": "employee",
                 "allowed_permissions": ["deliveries", "deliveries_assign"]}
    assert _has_permission(emp_grant, "deliveries_assign") is True

    # empleado solo con "deliveries" → NO.
    emp_only_deliveries = {"role": "employee", "allowed_permissions": ["deliveries"]}
    assert _has_permission(emp_only_deliveries, "deliveries_assign") is False
    # …pero SÍ puede gestionar entregas.
    assert _has_permission(emp_only_deliveries, "deliveries") is True

    # empleado con lista vacía → NO asigna (EL FIX)…
    emp_empty = {"role": "employee", "allowed_permissions": []}
    assert _has_permission(emp_empty, "deliveries_assign") is False
    # …pero conserva el acceso heredado al resto (compatibilidad).
    assert _has_permission(emp_empty, "deliveries") is True
    assert _has_permission(emp_empty, "orders") is True
    assert _has_permission(emp_empty, "kyc") is True

    # empleado SIN el campo → NO asigna (EL FIX).
    emp_absent = {"role": "employee"}
    assert _has_permission(emp_absent, "deliveries_assign") is False
    assert _has_permission(emp_absent, "deliveries") is True

    # cliente / mensajero no-empleado → NO (control).
    assert _has_permission({"role": "normal"}, "deliveries_assign") is False
    assert _has_permission({"role": "vip", "is_courier": True}, "deliveries_assign") is False


# ------------------------------------------------------------------
# 2. Gate HTTP sobre /admin/deliveries/{id}/assign
# ------------------------------------------------------------------

def _assign(tok, courier_id="user_does_not_exist"):
    return requests.post(
        f"{API}/admin/deliveries/_nonexistent_/assign",
        headers=_hdr(tok), json={"courier_id": courier_id}, timeout=15)


def test_employee_empty_perms_blocked_from_assign():
    _unset_perms("user_test_employee01")
    r = _assign(EMPLOYEE_TOKEN)
    assert r.status_code == 403, r.text
    assert "Asignar mensajería" in r.text


def test_employee_only_deliveries_blocked_from_assign():
    _set_perms("user_test_employee01", ["deliveries"])
    r = _assign(EMPLOYEE_TOKEN)
    assert r.status_code == 403, r.text
    _unset_perms("user_test_employee01")


def test_employee_with_explicit_grant_passes_gate():
    _set_perms("user_test_employee01", ["deliveries", "deliveries_assign"])
    r = _assign(EMPLOYEE_TOKEN)
    # Pasa el gate de permiso; falla DESPUÉS porque el courier no existe.
    assert r.status_code != 403, r.text
    assert r.status_code == 400
    assert "mensajero" in r.text.lower()
    _unset_perms("user_test_employee01")


def test_admin_passes_gate():
    r = _assign(ADMIN_TOKEN)
    assert r.status_code != 403, r.text
    assert r.status_code == 400
    assert "mensajero" in r.text.lower()


def test_non_staff_blocked_from_assign():
    r = _assign(NORMAL_TOKEN)
    assert r.status_code == 403, r.text


def test_employee_empty_perms_still_manages_deliveries():
    """Compatibilidad: la lista vacía NO retira el acceso a gestionar
    entregas (permiso `deliveries`) — solo bloquea el asignar."""
    _unset_perms("user_test_employee01")
    r = requests.get(f"{API}/admin/deliveries", headers=_hdr(EMPLOYEE_TOKEN), timeout=15)
    assert r.status_code == 200, r.text
