"""iter55.16 — Granular per-staff permissions (RBAC-lite).

Covers:
1.  Permission catalog endpoint returns the 12 codes.
2.  `_has_permission()` predicate logic: admin passes / employee-empty passes /
    employee-with-code passes / employee-without-code fails / normal fails.
3.  PATCH /admin/users/{id} accepts `allowed_permissions` (admin only).
4.  Employees CANNOT modify other employees' permissions (only admins can).
5.  Sanitization rejects unknown permission codes.
6.  End-to-end gate on `require_permission`-protected routes:
      - Admin passes all.
      - Employee with empty list passes all (backward compat).
      - Employee with narrow list (e.g. ["kyc"]) passes /admin/kyc/* only.
      - Employee without "kyc" gets 403 with a helpful message.
7.  Legacy `can_manage_blocklist=false` employees still work as before when
    they get `allowed_permissions=[]` (backward compat).
"""
import os
import asyncio
import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN, VIP_TOKEN,
    with_totp_admin, with_totp_employee,
)

API = f"{BASE_URL}/api"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


def _set_perms(user_id: str, perms):
    """Direct DB write — bypasses the admin API so tests are independent."""
    _sync_db().users.update_one(
        {"user_id": user_id},
        {"$set": {"allowed_permissions": list(perms)}},
    )


def _reset_perms():
    _sync_db().users.update_many(
        {"user_id": {"$in": ["user_test_employee01", "user_test_admin01", "user_test_normal01"]}},
        {"$unset": {"allowed_permissions": ""}},
    )


def setup_module(module):
    _reset_perms()


def teardown_module(module):
    _reset_perms()


# ------------------------------------------------------------------
# 1. Catalog endpoint
# ------------------------------------------------------------------

def test_permissions_catalog_returns_13_items():
    # iter55.33 — 3 new codes added (user_stats, user_functions,
    # view_user_sensitive). Baseline lifted from 13 → 16 items.
    r = requests.get(f"{API}/admin/permissions/catalog", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 16
    codes = {i["code"] for i in items}
    assert codes == {
        "orders", "withdrawals", "kyc", "appeals", "products", "rates",
        "currencies", "users", "company_funds", "blocked_contacts",
        "transactions", "quick_view", "profile_changes",
        "user_stats", "user_functions", "view_user_sensitive",
    }
    # Each item has label + description
    for it in items:
        assert "label" in it and it["label"]
        assert "description" in it and it["description"]


def test_permissions_catalog_accessible_by_staff():
    r = requests.get(f"{API}/admin/permissions/catalog", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 200


def test_permissions_catalog_forbidden_for_non_staff():
    r = requests.get(f"{API}/admin/permissions/catalog", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 403


# ------------------------------------------------------------------
# 2. Predicate logic (pure — no HTTP)
# ------------------------------------------------------------------

def test_has_permission_predicate():
    from services.permissions import _has_permission

    admin = {"role": "admin"}
    assert _has_permission(admin, "kyc") is True
    assert _has_permission(admin, "orders") is True

    employee_open = {"role": "employee", "allowed_permissions": []}
    assert _has_permission(employee_open, "kyc") is True
    assert _has_permission(employee_open, "orders") is True

    employee_kyc = {"role": "employee", "allowed_permissions": ["kyc"]}
    assert _has_permission(employee_kyc, "kyc") is True
    assert _has_permission(employee_kyc, "orders") is False
    assert _has_permission(employee_kyc, "withdrawals") is False

    normal = {"role": "normal"}
    assert _has_permission(normal, "kyc") is False

    vip = {"role": "vip"}
    assert _has_permission(vip, "kyc") is False


# ------------------------------------------------------------------
# 3. PUT /admin/users/{id} accepts allowed_permissions
# ------------------------------------------------------------------

def test_admin_can_grant_kyc_permission_to_employee():
    _reset_perms()
    r = requests.put(
        f"{API}/admin/users/user_test_employee01",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({"allowed_permissions": ["kyc", "appeals"]}),
    )
    assert r.status_code == 200, r.text
    u = _sync_db().users.find_one({"user_id": "user_test_employee01"})
    assert set(u["allowed_permissions"]) == {"kyc", "appeals"}
    _reset_perms()


def test_admin_can_clear_permissions():
    _set_perms("user_test_employee01", ["kyc"])
    r = requests.put(
        f"{API}/admin/users/user_test_employee01",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({"allowed_permissions": []}),
    )
    assert r.status_code == 200
    u = _sync_db().users.find_one({"user_id": "user_test_employee01"})
    assert u["allowed_permissions"] == []
    _reset_perms()


# ------------------------------------------------------------------
# 4. Employees cannot modify permissions (admin-only guard)
# ------------------------------------------------------------------

def test_employee_cannot_modify_permissions_of_others():
    _reset_perms()
    r = requests.put(
        f"{API}/admin/users/user_test_normal01",
        headers=_hdr(EMPLOYEE_TOKEN),
        json=with_totp_employee({"allowed_permissions": ["kyc"]}),
    )
    assert r.status_code == 403
    assert "admin" in r.json()["detail"].lower()


# ------------------------------------------------------------------
# 5. Sanitization — unknown codes silently dropped
# ------------------------------------------------------------------

def test_unknown_permission_codes_are_dropped():
    _reset_perms()
    r = requests.put(
        f"{API}/admin/users/user_test_employee01",
        headers=_hdr(ADMIN_TOKEN),
        json=with_totp_admin({"allowed_permissions": ["kyc", "hackerman", "SUPER_ADMIN", "orders"]}),
    )
    assert r.status_code == 200
    u = _sync_db().users.find_one({"user_id": "user_test_employee01"})
    assert set(u["allowed_permissions"]) == {"kyc", "orders"}
    _reset_perms()


# ------------------------------------------------------------------
# 6. End-to-end gate — /admin/kyc/queue
# ------------------------------------------------------------------

def test_employee_with_kyc_perm_can_access_kyc_queue():
    _set_perms("user_test_employee01", ["kyc"])
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 200
    _reset_perms()


def test_employee_without_kyc_perm_gets_403_on_kyc_queue():
    _set_perms("user_test_employee01", ["orders"])  # no "kyc"
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 403
    assert "KYC" in r.json()["detail"] or "kyc" in r.json()["detail"].lower()
    _reset_perms()


def test_employee_with_empty_perms_backward_compatible():
    """Regression — existing employees with allowed_permissions unset/empty
    must retain access to all staff pages (backward compat rule)."""
    _reset_perms()
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 200


def test_admin_never_gated_regardless_of_perms():
    """Admin is the root role — even if allowed_permissions is [], they pass."""
    _set_perms("user_test_admin01", [])
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    r2 = requests.get(f"{API}/admin/withdrawals", headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 200
    _reset_perms()


def test_normal_user_still_blocked_from_admin_routes():
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 403
    r2 = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(VIP_TOKEN))
    assert r2.status_code == 403


# ------------------------------------------------------------------
# 7. Narrow scope: employee with ["kyc"] cannot touch orders/withdrawals
# ------------------------------------------------------------------

def test_narrow_scope_employee_kyc_only():
    _set_perms("user_test_employee01", ["kyc"])
    # KYC allowed
    assert requests.get(f"{API}/admin/kyc/queue", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 200
    # Orders blocked
    assert requests.get(f"{API}/admin/orders", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 403
    # Withdrawals blocked
    assert requests.get(f"{API}/admin/withdrawals", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 403
    # Transactions blocked
    assert requests.get(f"{API}/admin/transactions", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 403
    # Users blocked
    assert requests.get(f"{API}/admin/users", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 403
    _reset_perms()


def test_narrow_scope_employee_orders_only():
    _set_perms("user_test_employee01", ["orders"])
    assert requests.get(f"{API}/admin/orders", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 200
    assert requests.get(f"{API}/admin/kyc/queue", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 403
    assert requests.get(f"{API}/admin/withdrawals", headers=_hdr(EMPLOYEE_TOKEN)).status_code == 403
    _reset_perms()


# ------------------------------------------------------------------
# 8. Backward compat for legacy booleans (blocklist + company_funds)
# ------------------------------------------------------------------

def test_new_permission_grants_legacy_blocklist_access():
    """iter55.16 — an employee with `blocked_contacts` in allowed_permissions
    but `can_manage_blocklist=false` should still access blocklist because the
    new permission system supersedes the legacy boolean."""
    _sync_db().users.update_one(
        {"user_id": "user_test_employee01"},
        {"$set": {"allowed_permissions": ["blocked_contacts"], "can_manage_blocklist": False}},
    )
    r = requests.get(f"{API}/admin/blocked-contacts", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 200
    _sync_db().users.update_one(
        {"user_id": "user_test_employee01"},
        {"$unset": {"allowed_permissions": "", "can_manage_blocklist": ""}},
    )
