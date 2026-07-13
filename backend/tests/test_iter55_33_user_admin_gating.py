"""iter55.33 — Permission-gated user list + stats + functions.

Operator feedback (12 Feb 2026): staff should still SEE the Estadísticas +
Funciones buttons in the users table, but if they lack the corresponding
granular permission the system should show "acceso restringido" instead of
letting them perform the action. Sensitive columns (phone, balance) also
gated by `view_user_sensitive`.

New permissions added to the catalog:
  - `user_stats`             → gates GET /admin/users/{id}/stats
  - `user_functions`         → gates PUT /admin/users/{id} when the payload
                              touches role/allowed_currencies/allowed_permissions/
                              market perms/account_status
  - `view_user_sensitive`    → gates the response of GET /admin/users (list)
                              stripping phone/vip_balances/vip_balance_usdt/
                              allowed_* on failure
"""
import os
import uuid
import bcrypt
import pyotp
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, ADMIN_TOKEN

API = f"{API_ROOT}/api"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

STAFF_UID = "user_test_staff_gated"
STAFF_EMAIL = "gated.staff@resilience.com"
STAFF_TOKEN = "test_session_staff_gated_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _totp():
    return pyotp.TOTP(TOTP_SECRET).now()


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _hash(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _setup_gated_staff(perms):
    """Provision a staff employee with a specific `allowed_permissions` list
    + an active session token so we can exercise the granular gates."""
    import totp_service as _ts
    doc = {
        "user_id": STAFF_UID,
        "email": STAFF_EMAIL,
        "name": "Gated Staff",
        "role": "employee",
        "auth_provider": "password",
        "password_hash": _hash("StaffPass1!"),
        "email_verified": True,
        "totp_enabled": True,
        "totp_secret_encrypted": _ts.encrypt_secret(TOTP_SECRET),
        "totp_recovery_codes": [],
        "totp_setup_at": _iso(),
        "account_status": "active",
        "allowed_permissions": perms,  # <<< the gate under test
        "created_at": _iso(),
    }
    _db().users.update_one({"user_id": STAFF_UID}, {"$set": doc}, upsert=True)
    now = datetime.now(timezone.utc)
    expires = now.replace(year=now.year + 1)
    _db().user_sessions.update_one(
        {"session_token": STAFF_TOKEN},
        {"$set": {"session_token": STAFF_TOKEN, "user_id": STAFF_UID,
                  "expires_at": expires, "created_at": now}},
        upsert=True,
    )


def _cleanup():
    _db().users.delete_many({"user_id": STAFF_UID})
    _db().user_sessions.delete_many({"user_id": STAFF_UID})


# ============================================================
# GET /admin/users — list column stripping
# ============================================================

def test_staff_without_view_user_sensitive_gets_stripped_list():
    """Staff with allowed_permissions=['users'] (list access but NOT
    view_user_sensitive) receives users WITHOUT phone/balance/permissions."""
    _setup_gated_staff(["users"])
    try:
        r = requests.get(f"{API}/admin/users", headers=_hdr(STAFF_TOKEN))
        assert r.status_code == 200, r.text
        docs = r.json()
        assert len(docs) > 0
        for d in docs:
            # These sensitive fields must be stripped
            assert "phone" not in d, f"phone leaked for staff: {d.get('email')}"
            assert "vip_balances" not in d
            assert "vip_balance_usdt" not in d
            assert "vip_balance_usd" not in d
            assert "allowed_permissions" not in d
            assert "allowed_currencies" not in d
            # But the non-sensitive fields must still be there
            assert "email" in d
            assert "role" in d
            assert "user_id" in d
    finally:
        _cleanup()


def test_staff_with_view_user_sensitive_sees_all_fields():
    """When the staff HAS view_user_sensitive, no stripping happens."""
    _setup_gated_staff(["users", "view_user_sensitive"])
    try:
        r = requests.get(f"{API}/admin/users", headers=_hdr(STAFF_TOKEN))
        assert r.status_code == 200, r.text
        docs = r.json()
        # At least ONE user must expose phone/balance (admin's own vip_balance
        # may be 0 but the KEY should still exist for enriched docs)
        any_with_balance_key = any("vip_balance_usdt" in d for d in docs)
        assert any_with_balance_key
    finally:
        _cleanup()


def test_admin_always_sees_all_fields():
    """Admin bypass — no filtering even without explicit view_user_sensitive."""
    r = requests.get(f"{API}/admin/users", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    docs = r.json()
    any_with_balance_key = any("vip_balance_usdt" in d for d in docs)
    assert any_with_balance_key


# ============================================================
# GET /admin/users/{id}/stats — user_stats gate
# ============================================================

def test_staff_without_user_stats_perm_gets_403():
    _setup_gated_staff(["users"])  # missing user_stats
    try:
        r = requests.get(f"{API}/admin/users/user_test_vip01/stats",
                          headers=_hdr(STAFF_TOKEN))
        assert r.status_code == 403, r.text
        # Message must reference the missing permission for UX clarity
        detail = r.json().get("detail", "")
        assert "permiso" in detail.lower() or "acceso" in detail.lower()
    finally:
        _cleanup()


def test_staff_with_user_stats_perm_can_read_stats():
    _setup_gated_staff(["users", "user_stats"])
    try:
        r = requests.get(f"{API}/admin/users/user_test_vip01/stats",
                          headers=_hdr(STAFF_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        # iter55.33 — new fields the stats endpoint MUST include
        assert "kyc" in body
        assert "success_rate_pct" in body["orders"]
        assert "favorite_currency" in body["orders"]
        assert "email_verified" in body["user"]
        assert "phone_verified" in body["user"]
        assert "twofa_enabled" in body["user"]
    finally:
        _cleanup()


def test_empty_permissions_grants_full_access_backward_compat():
    """iter55.16 semantics preserved: an employee with allowed_permissions=[]
    still gets full access (no stripping, no 403). This protects existing
    employees whose docs pre-date iter55.33."""
    _setup_gated_staff([])  # legacy: empty list = full access
    try:
        r = requests.get(f"{API}/admin/users/user_test_vip01/stats",
                          headers=_hdr(STAFF_TOKEN))
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{API}/admin/users", headers=_hdr(STAFF_TOKEN))
        docs = r2.json()
        any_with_balance = any("vip_balance_usdt" in d for d in docs)
        assert any_with_balance
    finally:
        _cleanup()


# ============================================================
# PUT /admin/users/{id} — user_functions gate
# ============================================================

def test_staff_without_user_functions_cannot_change_role():
    """Staff with `users` perm but NO `user_functions` → 403 when trying
    to change a user's role. Backward-compat with legacy employees (empty
    perms list) is preserved by the earlier test."""
    _setup_gated_staff(["users"])
    try:
        r = requests.put(
            f"{API}/admin/users/user_test_normal01",
            headers=_hdr(STAFF_TOKEN),
            json={"role": "vip", "totp_code": _totp()},
        )
        assert r.status_code == 403, r.text
        assert "Funciones de usuario" in r.json()["detail"]
    finally:
        _cleanup()


def test_staff_with_user_functions_can_change_role():
    _setup_gated_staff(["users", "user_functions"])
    # Backup previous role
    prev = _db().users.find_one({"user_id": "user_test_normal01"},
                                  {"role": 1, "_id": 0})
    try:
        r = requests.put(
            f"{API}/admin/users/user_test_normal01",
            headers=_hdr(STAFF_TOKEN),
            json={"role": "vip", "totp_code": _totp()},
        )
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "vip"
    finally:
        # Restore
        _db().users.update_one({"user_id": "user_test_normal01"},
                                 {"$set": {"role": prev.get("role", "normal")}})
        _cleanup()


def test_staff_without_user_functions_can_still_verify_email():
    """Verify-email endpoint is a separate flow (no FUNCTIONS_FIELDS involved)
    → should NOT be blocked by the new gate. Existing UX must keep working."""
    _setup_gated_staff(["users"])
    # Plant a normal user with email_verified=false
    _db().users.update_one({"user_id": "user_test_normal01"},
                             {"$set": {"email_verified": False}})
    try:
        r = requests.post(
            f"{API}/admin/users/user_test_normal01/verify-email",
            headers=_hdr(STAFF_TOKEN),
            json={"totp_code": _totp()},
        )
        # 200 OR 400 (already verified) but MUST NOT be 403 for user_functions
        assert r.status_code != 403
    finally:
        _db().users.update_one({"user_id": "user_test_normal01"},
                                 {"$set": {"email_verified": True}})
        _cleanup()


# ============================================================
# Permission catalog exposes the new codes
# ============================================================

def test_permission_catalog_includes_new_codes():
    r = requests.get(f"{API}/admin/permissions/catalog", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()["items"]}
    assert "user_stats" in codes
    assert "user_functions" in codes
    assert "view_user_sensitive" in codes
