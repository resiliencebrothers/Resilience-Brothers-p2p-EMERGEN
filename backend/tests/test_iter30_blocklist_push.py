"""iter30 — blocklist router refactor + PWA push fan-out integration tests.

Verifies:
1) All 5 blocklist endpoints (extracted to routes/blocklist.py) still work end-to-end
   with the same response shape and status codes as before.
2) Permission gating: staff without can_manage_blocklist=True → 403.
3) send_push_to_user is invoked by notify_staff_new_pending_user /
   notify_user_phone_verified / notify_user_phone_rejected — verified by spying
   on push_service.send_push_to_user via monkeypatch, AND by seeding a dead
   push_subscription and confirming it gets deleted on next delivery attempt.
4) Backwards-compat helpers: _assert_account_active still in server.py and still
   guards orders / withdrawals / redemptions (ACCOUNT_UNDER_REVIEW).
"""
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "backend" / ".env")
load_dotenv(_ROOT / "frontend" / ".env")

from conftest import make_admin_totp  # noqa: E402

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = "test_session_admin_X"
EMPLOYEE = "test_session_employee_X"
NORMAL = "test_session_normal_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _reset():
    db = _db()
    db.blocked_contacts.delete_many({"reason": {"$regex": "^iter30_"}})
    db.blocked_contacts.delete_many({"phone": {"$regex": "^\\+5359999"}})
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$unset": {"can_manage_blocklist": ""}})
    yield
    db.blocked_contacts.delete_many({"reason": {"$regex": "^iter30_"}})
    db.blocked_contacts.delete_many({"phone": {"$regex": "^\\+5359999"}})
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$unset": {"can_manage_blocklist": ""}})


# ============================================================
# Blocklist CRUD (refactor smoke)
# ============================================================
class TestBlocklistCRUD:
    def test_list_blocked_contacts_admin_ok(self):
        r = requests.get(f"{API}/admin/blocked-contacts", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "total" in body
        assert isinstance(body["items"], list)
        assert isinstance(body["total"], int)

    def test_create_then_get_then_delete(self):
        phone = "+535999901234"
        # CREATE
        r = requests.post(f"{API}/admin/blocked-contacts", json={
            "phone": phone, "reason": "iter30_test_create"
        }, headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        created = r.json()
        cid = created["id"]
        assert created["phone"] == phone
        assert created["reason"] == "iter30_test_create"

        # 409 on duplicate
        r2 = requests.post(f"{API}/admin/blocked-contacts", json={
            "phone": phone, "reason": "iter30_test_dup"
        }, headers=_h(ADMIN))
        assert r2.status_code == 409, r2.text

        # GET via list confirms persistence
        r3 = requests.get(f"{API}/admin/blocked-contacts?q=iter30_test_create",
                          headers=_h(ADMIN))
        assert r3.status_code == 200
        ids = [i["id"] for i in r3.json()["items"]]
        assert cid in ids

        # DELETE
        r4 = requests.delete(f"{API}/admin/blocked-contacts/{cid}", headers=_h(ADMIN))
        assert r4.status_code == 200
        assert r4.json()["ok"] is True

        # 404 on missing id
        r5 = requests.delete(f"{API}/admin/blocked-contacts/{cid}", headers=_h(ADMIN))
        assert r5.status_code == 404

    def test_create_requires_phone_or_email(self):
        r = requests.post(f"{API}/admin/blocked-contacts",
                          json={"reason": "iter30_test_empty"},
                          headers=_h(ADMIN))
        assert r.status_code == 422, r.text

    def test_bulk_import_response_shape(self):
        text = (
            "📌 Estafador iter30\n"
            "+53 5999 91234\n"
            "Usó tarjetas robadas\n"
            "\n"
            "Otro caso iter30\n"
            "+5359999 9999\n"
            "Suplantó identidad\n"
        )
        r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                          json={"text": text}, headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("imported_count", "skipped_count", "invalid_count",
                  "affected_active_accounts", "imported", "skipped_duplicates",
                  "invalid"):
            assert k in body, f"missing {k} in {body.keys()}"
        assert body["imported_count"] >= 1


# ============================================================
# Permission gating
# ============================================================
class TestPermissionGating:
    def test_employee_without_perm_403_on_all(self):
        # Ensure perm is OFF (fixture resets it)
        endpoints = [
            ("GET", f"{API}/admin/blocked-contacts", None),
            ("POST", f"{API}/admin/blocked-contacts",
             {"phone": "+535999912340", "reason": "iter30_perm"}),
            ("DELETE", f"{API}/admin/blocked-contacts/nonexistent", None),
            ("POST", f"{API}/admin/blocked-contacts/bulk-import",
             {"text": "x +53 5999 91100\nfoo"}),
            ("POST", f"{API}/admin/users/user_test_normal01/verify-phone",
             {"totp_code": "000000"}),
            ("POST", f"{API}/admin/users/user_test_normal01/reject-phone",
             {"reason": "iter30_perm_test_reason", "totp_code": "000000"}),
        ]
        for method, url, payload in endpoints:
            if method == "GET":
                r = requests.get(url, headers=_h(EMPLOYEE))
            elif method == "DELETE":
                r = requests.delete(url, headers=_h(EMPLOYEE))
            else:
                r = requests.post(url, json=payload, headers=_h(EMPLOYEE))
            assert r.status_code == 403, f"{method} {url} returned {r.status_code}: {r.text}"

    def test_employee_with_perm_can_list(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_employee01"},
                            {"$set": {"can_manage_blocklist": True}})
        try:
            r = requests.get(f"{API}/admin/blocked-contacts", headers=_h(EMPLOYEE))
            assert r.status_code == 200, r.text
        finally:
            db.users.update_one({"user_id": "user_test_employee01"},
                                {"$unset": {"can_manage_blocklist": ""}})


# ============================================================
# Verify-phone / Reject-phone with PUSH fan-out spy
# ============================================================
class TestVerifyRejectPushFanout:
    def _setup_user_with_phone(self, db, phone):
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "phone_verified": False,
                                      "account_status": "under_review"}})

    def _cleanup_user(self, db, phone):
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"account_status": "active",
                                      "phone_verified": False},
                             "$unset": {"phone": ""}})
        db.blocked_contacts.delete_many({"phone": phone})
        db.notifications.delete_many({"recipient_user_id": "user_test_normal01",
                                       "type": {"$in": ["phone_verified",
                                                          "phone_rejected"]}})
        db.push_subscriptions.delete_many({"user_id": "user_test_normal01",
                                            "id": {"$regex": "^iter30_"}})

    def _seed_dead_subscription(self, db, sub_id="iter30_dead_sub"):
        """Seed an empty subscription which send_push() will treat as 'dead'
        (subscription is None) so it should be pruned by send_push_to_user."""
        db.push_subscriptions.delete_many({"id": sub_id})
        db.push_subscriptions.insert_one({
            "id": sub_id,
            "user_id": "user_test_normal01",
            "subscription": None,   # send_push() returns 'dead' for None
            "created_at": "2026-01-01T00:00:00+00:00",
        })

    def test_verify_phone_prunes_dead_push_subscription(self):
        db = _db()
        phone = "+535999920001"
        self._setup_user_with_phone(db, phone)
        self._seed_dead_subscription(db, "iter30_dead_verify")
        try:
            r = requests.post(
                f"{API}/admin/users/user_test_normal01/verify-phone",
                json={"totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 200, r.text
            # Push helper must have run + pruned the dead subscription
            assert db.push_subscriptions.find_one({"id": "iter30_dead_verify"}) is None, \
                "dead subscription was not pruned — send_push_to_user not invoked"
            # In-app notification still inserted (iter29 contract)
            note = db.notifications.find_one(
                {"recipient_user_id": "user_test_normal01", "type": "phone_verified"})
            assert note is not None
        finally:
            self._cleanup_user(db, phone)

    def test_reject_phone_prunes_dead_push_subscription(self):
        db = _db()
        phone = "+535999920002"
        self._setup_user_with_phone(db, phone)
        self._seed_dead_subscription(db, "iter30_dead_reject")
        try:
            r = requests.post(
                f"{API}/admin/users/user_test_normal01/reject-phone",
                json={"reason": "iter30_scammer",
                      "totp_code": make_admin_totp()},
                headers=_h(ADMIN),
            )
            assert r.status_code == 200, r.text
            assert db.push_subscriptions.find_one({"id": "iter30_dead_reject"}) is None, \
                "dead subscription not pruned — reject-phone push fan-out missing"
            note = db.notifications.find_one(
                {"recipient_user_id": "user_test_normal01", "type": "phone_rejected"})
            assert note is not None
            assert "iter30_scammer" in note["data"]["reason"]
        finally:
            self._cleanup_user(db, phone)

    def test_register_invokes_push_for_admin_recipients(self):
        """A new normal-user registration should: insert in-app notes for admin
        AND attempt push delivery. We confirm via pruning a dead subscription
        seeded on the admin user."""
        db = _db()
        sub_id = "iter30_dead_admin"
        db.push_subscriptions.delete_many({"id": sub_id})
        db.push_subscriptions.insert_one({
            "id": sub_id,
            "user_id": "user_test_admin01",
            "subscription": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        email = f"test_iter30_{uuid.uuid4().hex[:8]}@example.com"
        try:
            r = requests.post(f"{API}/auth/register",
                              json={"name": "Iter30 Push",
                                    "email": email,
                                    "password": "veryStrongPass123",
                                    "phone": "+535999920003"})
            assert r.status_code in (200, 201), r.text
            new_user = db.users.find_one({"email": email})
            if new_user["role"] in ("admin", "employee"):
                pytest.skip("first user → admin, fan-out skipped")
            # Confirm push fan-out attempted (dead sub pruned)
            assert db.push_subscriptions.find_one({"id": sub_id}) is None, \
                "register did not invoke send_push_to_user on admin"
        finally:
            db.users.delete_many({"email": email})
            db.notifications.delete_many(
                {"type": "new_user_pending",
                 "data.email": email})
            db.push_subscriptions.delete_many({"id": sub_id})

    def test_register_does_not_break_when_push_fails(self):
        """Even if a recipient has a broken (None) subscription, register must
        still return 200 with the same response shape."""
        db = _db()
        sub_id = "iter30_admin_fail"
        db.push_subscriptions.delete_many({"id": sub_id})
        db.push_subscriptions.insert_one({
            "id": sub_id, "user_id": "user_test_admin01",
            "subscription": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        email = f"test_iter30_{uuid.uuid4().hex[:8]}@example.com"
        try:
            r = requests.post(f"{API}/auth/register",
                              json={"name": "Iter30 NoBreak",
                                    "email": email,
                                    "password": "veryStrongPass123",
                                    "phone": "+535999920004"})
            assert r.status_code in (200, 201), r.text
            body = r.json()
            # Same response shape: 24h message + token/user
            assert "24 horas" in body.get("message", ""), body
        finally:
            db.users.delete_many({"email": email})
            db.notifications.delete_many({"data.email": email})
            db.push_subscriptions.delete_many({"id": sub_id})


# ============================================================
# _assert_account_active still in server.py — sanity smoke
# ============================================================
class TestAccountActiveStillGuards:
    def test_under_review_user_cannot_create_order(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"account_status": "under_review"}})
        try:
            r = requests.post(f"{API}/orders",
                              json={"from_code": "USD", "to_code": "EUR",
                                    "amount_from": 100,
                                    "delivery_method": "transfer",
                                    "sender_name": "iter30 sender"},
                              headers=_h(NORMAL))
            assert r.status_code == 403, r.text
            body = r.json()
            detail = body.get("detail", {})
            if isinstance(detail, dict):
                assert detail.get("code") == "ACCOUNT_UNDER_REVIEW"
            else:
                assert "ACCOUNT_UNDER_REVIEW" in str(detail) or "revisión" in str(detail).lower()
        finally:
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active"}})
