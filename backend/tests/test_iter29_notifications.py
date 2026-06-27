"""iter29 — In-app notifications system backend tests.

Covers:
- Fan-out to admin + employees with can_manage_blocklist=True on register / /me/phone
- No fan-out for admin/employee registrations
- No fan-out on /me/phone *update* (already had a phone) — no spam
- verify-phone → phone_verified notification for target user
- reject-phone → phone_rejected notification with data.reason
- GET /api/notifications scoped to current user (no cross-user leak)
- unread-count, mark-read (idempotency + cross-user no-leak), mark-all-read
- /auth/register response message contains '24 horas'
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
VIP = "test_session_vip_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- House-keeping ----------
@pytest.fixture(autouse=True)
def cleanup_notifications_and_users():
    db = _db()
    # Remove notification rows from prior iter29 runs to keep counts predictable
    db.notifications.delete_many({"data.email": {"$regex": "^test_iter29_"}})
    # Reset employee perm + remove any test users
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$unset": {"can_manage_blocklist": ""}})
    db.users.delete_many({"email": {"$regex": "^test_iter29_"}})
    yield
    db.notifications.delete_many({"data.email": {"$regex": "^test_iter29_"}})
    db.users.delete_many({"email": {"$regex": "^test_iter29_"}})
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$unset": {"can_manage_blocklist": ""}})


# ============================================================
# Register fan-out & 24h message
# ============================================================
class TestRegisterFanout:
    def test_register_normal_user_fanout_to_admin_and_perm_employees(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_employee01"},
                            {"$set": {"can_manage_blocklist": True}})
        email = f"test_iter29_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register",
                          json={"name": "Iter29 New", "email": email,
                                "password": "veryStrongPass123",
                                "phone": "+5359990029"})
        assert r.status_code in (200, 201), r.text
        body = r.json()
        # 24h message present
        assert "24 horas" in body.get("message", ""), body
        new_user = db.users.find_one({"email": email}, {"_id": 0})
        assert new_user is not None
        if new_user["role"] in ("admin", "employee"):
            pytest.skip("first user became admin — fan-out logic skipped by design")

        # Find notifications for THIS new user
        notes = list(db.notifications.find(
            {"type": "new_user_pending", "data.target_user_id": new_user["user_id"]},
            {"_id": 0}))
        recipients = {n["recipient_user_id"] for n in notes}
        # Admin must receive one
        assert "user_test_admin01" in recipients, f"admin missing in {recipients}"
        # Employee with perm must receive one
        assert "user_test_employee01" in recipients, f"employee missing in {recipients}"
        # Validate the document shape on admin's row
        admin_note = next(n for n in notes if n["recipient_user_id"] == "user_test_admin01")
        assert admin_note["type"] == "new_user_pending"
        assert admin_note["read"] is False
        assert admin_note["data"]["target_user_id"] == new_user["user_id"]
        assert admin_note["data"]["email"] == email
        assert admin_note["data"]["phone"] == "+5359990029"
        assert admin_note["data"]["name"] == "Iter29 New"

    def test_employee_without_perm_does_not_receive_fanout(self):
        db = _db()
        # employee perm is unset by fixture
        email = f"test_iter29_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register",
                          json={"name": "Iter29 NoPerm", "email": email,
                                "password": "veryStrongPass123",
                                "phone": "+5359990030"})
        assert r.status_code in (200, 201), r.text
        new_user = db.users.find_one({"email": email})
        if new_user["role"] in ("admin", "employee"):
            pytest.skip("first user became admin — fan-out skipped")
        notes = list(db.notifications.find(
            {"type": "new_user_pending",
             "data.target_user_id": new_user["user_id"],
             "recipient_user_id": "user_test_employee01"}))
        assert notes == [], f"employee without perm got a fan-out: {notes}"
        # Admin still got it
        admin_notes = list(db.notifications.find(
            {"type": "new_user_pending",
             "data.target_user_id": new_user["user_id"],
             "recipient_user_id": "user_test_admin01"}))
        assert len(admin_notes) == 1


# ============================================================
# Verify / Reject phone → user notification
# ============================================================
class TestVerifyRejectNotifications:
    def test_verify_phone_creates_phone_verified_notification(self):
        db = _db()
        phone = "+5359990041"
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "phone_verified": False,
                                      "account_status": "under_review"}})
        # Wipe any prior phone_verified notes for normal user
        db.notifications.delete_many({"recipient_user_id": "user_test_normal01",
                                       "type": "phone_verified"})
        try:
            r = requests.post(f"{API}/admin/users/user_test_normal01/verify-phone",
                              json={"totp_code": make_admin_totp()},
                              headers=_hdr(ADMIN))
            assert r.status_code == 200, r.text
            notes = list(db.notifications.find(
                {"recipient_user_id": "user_test_normal01", "type": "phone_verified"}))
            assert len(notes) == 1
            n = notes[0]
            assert n["title"] == "¡Tu cuenta está activa!"
            assert n["read"] is False

            # Via the API the user should see it
            r2 = requests.get(f"{API}/notifications", headers=_hdr(NORMAL))
            assert r2.status_code == 200, r2.text
            items = r2.json()["items"]
            types = [i["type"] for i in items]
            assert "phone_verified" in types
        finally:
            db.notifications.delete_many({"recipient_user_id": "user_test_normal01",
                                           "type": "phone_verified"})
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})

    def test_reject_phone_creates_phone_rejected_notification_with_reason(self):
        db = _db()
        phone = "+5359990042"
        reason = "Caught scammer iter29 reason"
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "phone_verified": False,
                                      "account_status": "under_review"}})
        db.notifications.delete_many({"recipient_user_id": "user_test_normal01",
                                       "type": "phone_rejected"})
        try:
            r = requests.post(f"{API}/admin/users/user_test_normal01/reject-phone",
                              json={"reason": reason,
                                    "totp_code": make_admin_totp()},
                              headers=_hdr(ADMIN))
            assert r.status_code == 200, r.text
            notes = list(db.notifications.find(
                {"recipient_user_id": "user_test_normal01", "type": "phone_rejected"}))
            assert len(notes) == 1
            n = notes[0]
            assert reason in n["message"]
            assert n["data"]["reason"] == reason
        finally:
            db.notifications.delete_many({"recipient_user_id": "user_test_normal01",
                                           "type": "phone_rejected"})
            db.blocked_contacts.delete_many({"phone": phone})
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})


# ============================================================
# GET /notifications scoping + count + mark-read + cross-user
# ============================================================
class TestEndpoints:
    def _seed_note(self, db, recipient, read=False):
        nid = uuid.uuid4().hex
        db.notifications.insert_one({
            "id": nid,
            "recipient_user_id": recipient,
            "type": "info",
            "title": "T",
            "message": "iter29 seed",
            "data": {"email": "test_iter29_seed@example.com"},
            "read": read,
            "created_at": "2026-01-01T00:00:00+00:00",
            "read_at": None,
        })
        return nid

    def test_list_scoped_to_current_user_no_leak(self):
        db = _db()
        normal_id = self._seed_note(db, "user_test_normal01")
        vip_id = self._seed_note(db, "user_test_vip01")
        try:
            r = requests.get(f"{API}/notifications", headers=_hdr(NORMAL))
            assert r.status_code == 200
            ids = [i["id"] for i in r.json()["items"]]
            assert normal_id in ids
            assert vip_id not in ids
        finally:
            db.notifications.delete_many({"id": {"$in": [normal_id, vip_id]}})

    def test_unread_count_and_mark_all_read(self):
        db = _db()
        ids = [self._seed_note(db, "user_test_normal01") for _ in range(3)]
        try:
            r = requests.get(f"{API}/notifications/unread-count", headers=_hdr(NORMAL))
            assert r.status_code == 200
            base_count = r.json()["count"]
            assert base_count >= 3
            # mark-all-read
            r2 = requests.post(f"{API}/notifications/mark-all-read", headers=_hdr(NORMAL))
            assert r2.status_code == 200
            assert r2.json()["ok"] is True
            r3 = requests.get(f"{API}/notifications/unread-count", headers=_hdr(NORMAL))
            assert r3.json()["count"] == 0
        finally:
            db.notifications.delete_many({"id": {"$in": ids}})

    def test_mark_read_idempotent(self):
        db = _db()
        nid = self._seed_note(db, "user_test_normal01")
        try:
            r = requests.post(f"{API}/notifications/{nid}/read", headers=_hdr(NORMAL))
            assert r.status_code == 200
            assert r.json().get("ok") is True
            # Second call should NOT 404, should return idempotent already_read
            r2 = requests.post(f"{API}/notifications/{nid}/read", headers=_hdr(NORMAL))
            assert r2.status_code == 200, r2.text
            body = r2.json()
            assert body.get("ok") is True
            assert body.get("already_read") is True
        finally:
            db.notifications.delete_many({"id": nid})

    def test_mark_read_other_users_notification_no_leak(self):
        db = _db()
        vip_nid = self._seed_note(db, "user_test_vip01")
        try:
            # NORMAL user tries to read VIP's notification
            r = requests.post(f"{API}/notifications/{vip_nid}/read", headers=_hdr(NORMAL))
            assert r.status_code == 200
            body = r.json()
            assert body.get("ok") is True
            assert body.get("already_read") is True
            # Verify the VIP's notification is untouched
            n = db.notifications.find_one({"id": vip_nid})
            assert n["read"] is False
            assert n["read_at"] is None
        finally:
            db.notifications.delete_many({"id": vip_nid})

    def test_mark_all_read_only_affects_current_user(self):
        db = _db()
        normal_ids = [self._seed_note(db, "user_test_normal01") for _ in range(2)]
        vip_ids = [self._seed_note(db, "user_test_vip01") for _ in range(2)]
        try:
            r = requests.post(f"{API}/notifications/mark-all-read", headers=_hdr(NORMAL))
            assert r.status_code == 200
            # VIP's notes still unread
            for vid in vip_ids:
                doc = db.notifications.find_one({"id": vid})
                assert doc["read"] is False
            # Normal's notes are read
            for nid in normal_ids:
                doc = db.notifications.find_one({"id": nid})
                assert doc["read"] is True
        finally:
            db.notifications.delete_many({"id": {"$in": normal_ids + vip_ids}})


# ============================================================
# /me/phone — first set fan-out vs subsequent updates no-op
# ============================================================
class TestMePhoneFanout:
    def test_first_phone_set_triggers_fanout_update_does_not(self):
        db = _db()
        # Reset normal user: no phone, role=normal
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"role": "normal", "phone_verified": False,
                                      "account_status": "under_review"},
                             "$unset": {"phone": ""}})
        # Wipe prior new_user_pending notes for normal user
        db.notifications.delete_many(
            {"type": "new_user_pending",
             "data.target_user_id": "user_test_normal01"})
        try:
            phone1 = "+5359990051"
            r = requests.post(f"{API}/me/phone", json={"phone": phone1},
                              headers=_hdr(NORMAL))
            assert r.status_code == 200, r.text

            cnt1 = db.notifications.count_documents(
                {"type": "new_user_pending",
                 "data.target_user_id": "user_test_normal01"})
            assert cnt1 >= 1, "expected fan-out on first phone set"

            # Now UPDATE the phone — should NOT add a new fan-out
            phone2 = "+5359990052"
            r2 = requests.post(f"{API}/me/phone", json={"phone": phone2},
                               headers=_hdr(NORMAL))
            assert r2.status_code == 200, r2.text
            cnt2 = db.notifications.count_documents(
                {"type": "new_user_pending",
                 "data.target_user_id": "user_test_normal01"})
            assert cnt2 == cnt1, f"fan-out triggered on update: {cnt1}->{cnt2}"
        finally:
            db.notifications.delete_many(
                {"type": "new_user_pending",
                 "data.target_user_id": "user_test_normal01"})
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})
