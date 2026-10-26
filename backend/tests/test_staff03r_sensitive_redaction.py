"""STAFF-03-R (auditoría residual) — ninguna respuesta de MUTACIÓN de usuario
puede exponer más que el LISTADO para el mismo actor.

El catálogo describe `users` como lectura SIN datos sensibles ni funciones. Un
operador con `users` pero SIN `view_user_sensitive` NO debe recibir phone,
vip_balances/vip_balance_usd ni allowed_permissions en la respuesta de
verify-email / verify-phone / update — igual que no los recibe en /admin/users.
Con `view_user_sensitive` sí los recibe (paridad con el listado). Las
credenciales (password_hash, secretos 2FA) jamás salen en ningún caso.
"""
import os
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, EMPLOYEE_TOKEN, with_totp_employee,
)

API = f"{BASE_URL}/api"
EMP = "user_test_employee01"
NORMAL = "user_test_normal01"

SENSITIVE = ("phone", "phone_verified_at", "vip_balances", "vip_balance_usd",
             "vip_balance_usdt", "allowed_currencies", "allowed_permissions",
             "applied_templates", "market_perms")
CREDS = ("password_hash", "password", "totp_secret_encrypted",
         "totp_recovery_codes", "verification_token")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _set(uid, fields):
    _db().users.update_one({"user_id": uid}, {"$set": fields})


def _unset(uid, fields):
    _db().users.update_one({"user_id": uid}, {"$unset": {f: "" for f in fields}})


def _seed_normal_sensitive():
    _set(NORMAL, {
        "phone": "+5355501234", "phone_verified_at": "2026-01-01T00:00:00+00:00",
        "vip_balance_usd": 123, "vip_balances": {"USD": 123},
        "allowed_permissions": [], "allowed_currencies": [],
    })


def _list_target(token):
    email = (_db().users.find_one({"user_id": NORMAL}, {"_id": 0, "email": 1})
             or {}).get("email") or NORMAL
    r = requests.get(f"{API}/admin/users", params={"q": email, "limit": 20},
                     headers=_hdr(token))
    assert r.status_code == 200, r.text
    rows = [u for u in r.json() if u.get("user_id") == NORMAL]
    assert rows, "target not found in list"
    return rows[0]


def _assert_no_sensitive(user):
    for k in SENSITIVE:
        assert k not in user, f"campo sensible '{k}' NO debía salir: {user.get(k)!r}"


def _assert_no_creds(user):
    for k in CREDS:
        assert k not in user, f"credencial '{k}' nunca debe salir"


# ------------------------------------------------------------------
# verify-email — operador con SOLO `users`
# ------------------------------------------------------------------

def test_staff03r_verify_email_already_verified_users_only_redacts():
    _set(EMP, {"allowed_permissions": ["users"]})
    _seed_normal_sensitive()
    _set(NORMAL, {"email_verified": True})
    try:
        r = requests.post(f"{API}/admin/users/{NORMAL}/verify-email",
                          headers=_hdr(EMPLOYEE_TOKEN), json=with_totp_employee({}))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["already_verified"] is True
        _assert_no_sensitive(body["user"])
        _assert_no_creds(body["user"])
        # Paridad con el listado para el MISMO actor.
        _assert_no_sensitive(_list_target(EMPLOYEE_TOKEN))
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff03r_verify_email_unverified_branch_users_only_redacts():
    _set(EMP, {"allowed_permissions": ["users"]})
    _seed_normal_sensitive()
    _set(NORMAL, {"email_verified": False})
    _unset(NORMAL, ["verification_token", "verification_expires_at"])
    try:
        r = requests.post(f"{API}/admin/users/{NORMAL}/verify-email",
                          headers=_hdr(EMPLOYEE_TOKEN), json=with_totp_employee({}))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["already_verified"] is False
        _assert_no_sensitive(body["user"])
        _assert_no_creds(body["user"])
    finally:
        _unset(EMP, ["allowed_permissions"])
        _set(NORMAL, {"email_verified": True})


# ------------------------------------------------------------------
# verify-email — operador AUTORIZADO (users + view_user_sensitive)
# ------------------------------------------------------------------

def test_staff03r_verify_email_authorized_includes_sensitive():
    _set(EMP, {"allowed_permissions": ["users", "view_user_sensitive"]})
    _seed_normal_sensitive()
    _set(NORMAL, {"email_verified": True})
    try:
        r = requests.post(f"{API}/admin/users/{NORMAL}/verify-email",
                          headers=_hdr(EMPLOYEE_TOKEN), json=with_totp_employee({}))
        assert r.status_code == 200, r.text
        user = r.json()["user"]
        # Con el permiso de datos, los campos sensibles SÍ llegan...
        assert user.get("phone") == "+5355501234"
        assert "vip_balance_usd" in user
        assert "allowed_permissions" in user
        # ...pero las credenciales NUNCA.
        _assert_no_creds(user)
        # Paridad: el listado para este actor también los muestra.
        lst = _list_target(EMPLOYEE_TOKEN)
        assert lst.get("phone") == "+5355501234"
    finally:
        _unset(EMP, ["allowed_permissions"])


# ------------------------------------------------------------------
# update_user — misma redacción en la respuesta de la mutación
# ------------------------------------------------------------------

def test_staff03r_update_user_response_redacted_for_users_only():
    # Empleado con users+user_functions (sin view_user_sensitive) edita el
    # ALCANCE de un cliente normal (permitido por STAFF-07) → la respuesta no
    # debe filtrar datos sensibles.
    _set(EMP, {"allowed_permissions": ["users", "user_functions"]})
    _seed_normal_sensitive()
    prev = (_db().users.find_one({"user_id": NORMAL}, {"allowed_currencies": 1, "_id": 0})
            or {}).get("allowed_currencies")
    try:
        r = requests.put(f"{API}/admin/users/{NORMAL}", headers=_hdr(EMPLOYEE_TOKEN),
                         json=with_totp_employee({"allowed_currencies": ["USD"]}))
        assert r.status_code == 200, r.text
        _assert_no_sensitive(r.json())
        _assert_no_creds(r.json())
    finally:
        _unset(EMP, ["allowed_permissions"])
        if prev is None:
            _unset(NORMAL, ["allowed_currencies"])
        else:
            _set(NORMAL, {"allowed_currencies": prev})


# ------------------------------------------------------------------
# verify-phone (blocklist) — restante mutación anidada de usuario
# ------------------------------------------------------------------

def test_staff03r_verify_phone_response_redacted_for_non_sensitive_actor():
    # Operador de bloqueos SIN view_user_sensitive → respuesta redactada.
    _set(EMP, {"allowed_permissions": ["blocked_contacts"]})
    _seed_normal_sensitive()
    _set(NORMAL, {"phone_verified": True, "account_status": "active"})
    _db().blocked_contacts.delete_many({"phone": "+5355501234"})
    try:
        r = requests.post(f"{API}/admin/users/{NORMAL}/verify-phone",
                          headers=_hdr(EMPLOYEE_TOKEN), json=with_totp_employee({}))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["already_verified"] is True
        _assert_no_sensitive(body["user"])
        _assert_no_creds(body["user"])
    finally:
        _unset(EMP, ["allowed_permissions"])


def test_staff03r_verify_phone_authorized_includes_phone():
    _set(EMP, {"allowed_permissions": ["blocked_contacts", "view_user_sensitive"]})
    _seed_normal_sensitive()
    _set(NORMAL, {"phone_verified": True, "account_status": "active"})
    _db().blocked_contacts.delete_many({"phone": "+5355501234"})
    try:
        r = requests.post(f"{API}/admin/users/{NORMAL}/verify-phone",
                          headers=_hdr(EMPLOYEE_TOKEN), json=with_totp_employee({}))
        assert r.status_code == 200, r.text
        user = r.json()["user"]
        assert user.get("phone") == "+5355501234"
        _assert_no_creds(user)
    finally:
        _unset(EMP, ["allowed_permissions"])
