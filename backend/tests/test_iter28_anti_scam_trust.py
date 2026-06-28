"""iter28 — Anti-scam Trust Layer (Phase 2) backend tests.

Covers:
- WhatsApp-aware bulk-import parser + endpoint
- Granular `can_manage_blocklist` permission gating
- ✅ Verify / 🚫 Reject phone actions
- New `account_status` field defaults & enforcement on client operations
- Login re-check against blocklist
"""
import os
import time

import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path
from pymongo import MongoClient

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "backend" / ".env")
load_dotenv(_ROOT / "frontend" / ".env")

from conftest import make_admin_totp, make_employee_totp  # noqa: E402

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


WHATSAPP_SAMPLE = (
    "Estafador ❌️ \n"
    "👇🏻\n"
    "+5359804084\n"
    "+5356455618\n"
    "+5358491802\n"
    "📌Son la misma persona \n"
    "📌Se hace pasar por comprador y vendedor de saldo\n"
    "📌Se hace pasar por Remesero"
)


@pytest.fixture(autouse=True, scope="module")
def cleanup_blocklist():
    """Wipe blocklist entries for the test phones before AND after the module."""
    db = _db()
    test_phones = ["+5359804084", "+5356455618", "+5358491802", "+5359998877", "+5359998866"]
    db.blocked_contacts.delete_many({"phone": {"$in": test_phones}})
    # Make sure employee starts WITHOUT can_manage_blocklist for our gating tests.
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$unset": {"can_manage_blocklist": ""}})
    # Make sure normal/vip start active and with no toxic phone.
    db.users.update_many(
        {"user_id": {"$in": ["user_test_normal01", "user_test_vip01"]}},
        {"$set": {"account_status": "active"}, "$unset": {}}
    )
    yield
    db.blocked_contacts.delete_many({"phone": {"$in": test_phones}})
    db.users.update_one({"user_id": "user_test_employee01"},
                        {"$unset": {"can_manage_blocklist": ""}})
    db.users.update_many(
        {"user_id": {"$in": ["user_test_normal01", "user_test_vip01"]}},
        {"$set": {"account_status": "active"}}
    )


# ============================================================
# Bulk-import parser & endpoint
# ============================================================
class TestBulkImport:
    def test_bulk_import_real_whatsapp_example(self):
        r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                          json={"text": WHATSAPP_SAMPLE}, headers=_hdr(ADMIN))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported_count"] == 3
        assert data["skipped_count"] == 0
        assert data["invalid_count"] == 0
        # Verify entries persisted with the expected name and multi-line reason
        db = _db()
        for ph in ["+5359804084", "+5356455618", "+5358491802"]:
            doc = db.blocked_contacts.find_one({"phone": ph}, {"_id": 0})
            assert doc is not None, f"missing imported phone {ph}"
            assert doc.get("name") == "Estafador ❌️"
            assert "Son la misma persona" in (doc.get("reason") or "")
            assert "comprador y vendedor" in (doc.get("reason") or "")
            assert "Remesero" in (doc.get("reason") or "")

    def test_bulk_import_dedupe_second_run(self):
        # Re-importing same text → all 3 should now be duplicates
        r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                          json={"text": WHATSAPP_SAMPLE}, headers=_hdr(ADMIN))
        assert r.status_code == 200
        d = r.json()
        assert d["imported_count"] == 0
        assert d["skipped_count"] == 3
        assert d["invalid_count"] == 0

    def test_bulk_import_multi_blocks(self):
        text = (
            "Block A\n+5359998877\n📌spam\n\n"
            "Block B (no phone here)\n📌nothing valuable\n\n"
            "Block C\n+5359998866\n📌double scam"
        )
        r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                          json={"text": text}, headers=_hdr(ADMIN))
        assert r.status_code == 200
        d = r.json()
        # 2 phones imported, B silently ignored, no invalids
        assert d["imported_count"] == 2
        assert d["skipped_count"] == 0
        assert d["invalid_count"] == 0
        # cleanup
        _db().blocked_contacts.delete_many({"phone": {"$in": ["+5359998877", "+5359998866"]}})

    def test_bulk_import_garbage_no_phones(self):
        r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                          json={"text": "hello world\nno phones here\njust text"},
                          headers=_hdr(ADMIN))
        assert r.status_code == 200
        d = r.json()
        assert d["imported_count"] == 0
        assert d["invalid_count"] == 0

    def test_bulk_import_freezes_existing_user_with_matching_phone(self):
        db = _db()
        # Set normal user's phone to one we're about to bulk-import
        phone = "+5359990001"
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "account_status": "active",
                                      "phone_verified": True}})
        try:
            r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                              json={"text": f"Scammer\n{phone}\n📌caught"},
                              headers=_hdr(ADMIN))
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["imported_count"] == 1
            assert data["affected_active_accounts"] >= 1
            # Confirm user got frozen
            u = db.users.find_one({"user_id": "user_test_normal01"})
            assert u["account_status"] == "under_review"
            assert u["phone_verified"] is False
        finally:
            db.blocked_contacts.delete_many({"phone": phone})
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})


# ============================================================
# Permission gating — can_manage_blocklist
# ============================================================
class TestPermissionGating:
    def test_employee_without_perm_blocked_on_blocklist_endpoints(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_employee01"},
                            {"$unset": {"can_manage_blocklist": ""}})

        # GET list
        r = requests.get(f"{API}/admin/blocked-contacts", headers=_hdr(EMPLOYEE))
        assert r.status_code == 403, r.text
        # POST single
        r = requests.post(f"{API}/admin/blocked-contacts",
                          json={"phone": "+5359000000", "reason": "test"},
                          headers=_hdr(EMPLOYEE))
        assert r.status_code == 403
        # POST bulk
        r = requests.post(f"{API}/admin/blocked-contacts/bulk-import",
                          json={"text": "x\n+5359990000\n"}, headers=_hdr(EMPLOYEE))
        assert r.status_code == 403
        # DELETE
        r = requests.delete(f"{API}/admin/blocked-contacts/nonexistent",
                            headers=_hdr(EMPLOYEE))
        assert r.status_code == 403
        # verify-phone
        r = requests.post(f"{API}/admin/users/user_test_normal01/verify-phone",
                          json={"totp_code": make_employee_totp()}, headers=_hdr(EMPLOYEE))
        assert r.status_code == 403
        # reject-phone
        r = requests.post(f"{API}/admin/users/user_test_normal01/reject-phone",
                          json={"reason": "scam test", "totp_code": make_employee_totp()},
                          headers=_hdr(EMPLOYEE))
        assert r.status_code == 403

    def test_employee_with_perm_can_list(self):
        db = _db()
        db.users.update_one({"user_id": "user_test_employee01"},
                            {"$set": {"can_manage_blocklist": True}})
        try:
            r = requests.get(f"{API}/admin/blocked-contacts", headers=_hdr(EMPLOYEE))
            assert r.status_code == 200
            assert "items" in r.json()
        finally:
            db.users.update_one({"user_id": "user_test_employee01"},
                                {"$unset": {"can_manage_blocklist": ""}})

    def test_admin_bypasses_perm_check(self):
        r = requests.get(f"{API}/admin/blocked-contacts", headers=_hdr(ADMIN))
        assert r.status_code == 200


# ============================================================
# Verify / Reject phone endpoints
# ============================================================
class TestVerifyReject:
    def test_verify_phone_blocked_returns_409(self):
        db = _db()
        phone = "+5359007777"
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "phone_verified": False,
                                      "account_status": "under_review"}})
        db.blocked_contacts.insert_one({"id": "blkx1", "phone": phone,
                                        "reason": "test-blocked",
                                        "created_at": "2026-01-01T00:00:00+00:00",
                                        "created_by": "admin"})
        try:
            r = requests.post(f"{API}/admin/users/user_test_normal01/verify-phone",
                              json={"totp_code": make_admin_totp()},
                              headers=_hdr(ADMIN))
            assert r.status_code == 409, r.text
            body = r.json()
            detail = body.get("detail", body)
            assert detail.get("code") == "PHONE_IS_BLOCKED"
            assert detail.get("blocked_entry", {}).get("phone") == phone
        finally:
            db.blocked_contacts.delete_many({"phone": phone})
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})

    def test_verify_phone_happy_path_activates_account(self):
        db = _db()
        phone = "+5359008888"
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "phone_verified": False,
                                      "account_status": "under_review"}})
        try:
            r = requests.post(f"{API}/admin/users/user_test_normal01/verify-phone",
                              json={"totp_code": make_admin_totp()},
                              headers=_hdr(ADMIN))
            assert r.status_code == 200, r.text
            u = r.json()["user"]
            assert u["phone_verified"] is True
            assert u["account_status"] == "active"
        finally:
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})

    def test_reject_phone_blocks_and_freezes(self):
        db = _db()
        phone = "+5359009999"
        db.blocked_contacts.delete_many({"phone": phone})
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"phone": phone, "phone_verified": False,
                                      "account_status": "under_review"}})
        try:
            r = requests.post(f"{API}/admin/users/user_test_normal01/reject-phone",
                              json={"reason": "Caught scammer",
                                    "notes": "evidence X",
                                    "totp_code": make_admin_totp()},
                              headers=_hdr(ADMIN))
            assert r.status_code == 200, r.text
            blocked = db.blocked_contacts.find_one({"phone": phone})
            assert blocked is not None
            assert blocked["reason"] == "Caught scammer"
            u = db.users.find_one({"user_id": "user_test_normal01"})
            assert u["phone_verified"] is False
            assert u["account_status"] == "under_review"

            # Idempotency: call again
            r2 = requests.post(f"{API}/admin/users/user_test_normal01/reject-phone",
                               json={"reason": "Caught scammer",
                                     "totp_code": make_admin_totp()},
                               headers=_hdr(ADMIN))
            assert r2.status_code == 200
            assert db.blocked_contacts.count_documents({"phone": phone}) == 1
        finally:
            db.blocked_contacts.delete_many({"phone": phone})
            db.users.update_one({"user_id": "user_test_normal01"},
                                {"$set": {"account_status": "active",
                                          "phone_verified": False},
                                 "$unset": {"phone": ""}})


# ============================================================
# Client operation gating
# ============================================================
class TestAccountStatusEnforcement:
    def _freeze(self, user_id):
        _db().users.update_one({"user_id": user_id},
                               {"$set": {"account_status": "under_review"}})

    def _restore(self, user_id):
        _db().users.update_one({"user_id": user_id},
                               {"$set": {"account_status": "active"}})

    def test_under_review_normal_user_cannot_create_order(self):
        self._freeze("user_test_normal01")
        try:
            r = requests.post(f"{API}/orders",
                              json={"from_code": "USD", "to_code": "CUP",
                                    "amount_from": 10,
                                    "delivery_method": "transfer",
                                    "sender_name": "Test Sender"},
                              headers=_hdr(NORMAL))
            assert r.status_code == 403, r.text
            body = r.json()
            detail = body.get("detail", body)
            assert detail.get("code") == "ACCOUNT_UNDER_REVIEW"
        finally:
            self._restore("user_test_normal01")

    def test_under_review_vip_user_cannot_withdraw(self):
        self._freeze("user_test_vip01")
        try:
            r = requests.post(f"{API}/vip/withdraw",
                              json={"amount_usd": 10, "currency": "USD",
                                    "method": "transfer", "details": "x",
                                    "beneficiary_name": "Tester",
                                    "totp_code": "000000"},
                              headers=_hdr(VIP))
            assert r.status_code == 403, r.text
            detail = r.json().get("detail", r.json())
            assert detail.get("code") == "ACCOUNT_UNDER_REVIEW"
        finally:
            self._restore("user_test_vip01")

    def test_under_review_vip_user_cannot_redeem(self):
        self._freeze("user_test_vip01")
        try:
            r = requests.post(f"{API}/vip/redeem",
                              json={"product_id": "nope", "quantity": 1},
                              headers=_hdr(VIP))
            assert r.status_code == 403, r.text
            detail = r.json().get("detail", r.json())
            assert detail.get("code") == "ACCOUNT_UNDER_REVIEW"
        finally:
            self._restore("user_test_vip01")

    def test_admin_bypasses_account_status_check(self):
        # Admin role should never be account-gated
        r = requests.get(f"{API}/auth/me", headers=_hdr(ADMIN))
        assert r.status_code == 200


# ============================================================
# Login re-check against blocklist
# ============================================================
class TestLoginRecheck:
    def test_login_freezes_account_when_phone_blocked(self):
        """Create a user via /auth/register, mark them active+verified, then add their
        phone to the blocklist and POST /auth/login → expect login OK but account
        re-frozen."""
        db = _db()
        email = "test_iter28_login@example.com"
        # iter38 — test-only credential. NOT a real secret.
        password = os.environ.get("TEST_USER_PASSWORD", "veryStrongPass123")
        phone = "+5359111222"
        db.users.delete_many({"email": email})
        db.blocked_contacts.delete_many({"phone": phone})

        # Register
        reg = requests.post(f"{API}/auth/register",
                            json={"name": "T28 Login", "email": email,
                                  "password": password, "phone": phone})
        if reg.status_code not in (200, 201):
            pytest.skip(f"register failed {reg.status_code} {reg.text}")
        # Mark active, verified, with phone — simulate a previously trusted user
        db.users.update_one({"email": email},
                            {"$set": {"phone": phone, "phone_verified": True,
                                      "email_verified": True,
                                      "account_status": "active",
                                      "role": "normal"}})
        # Now block their phone
        db.blocked_contacts.insert_one({"id": "blkLogin1", "phone": phone,
                                        "reason": "test",
                                        "created_at": "2026-01-01T00:00:00+00:00",
                                        "created_by": "admin"})
        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": password})
            assert r.status_code == 200, r.text
            # Verify in DB that account_status got flipped
            u = db.users.find_one({"email": email})
            assert u["account_status"] == "under_review"
            assert u["phone_verified"] is False
        finally:
            db.users.delete_many({"email": email})
            db.blocked_contacts.delete_many({"phone": phone})

    def test_register_default_account_status_under_review_for_normal(self):
        db = _db()
        email = "test_iter28_reg@example.com"
        db.users.delete_many({"email": email})
        try:
            r = requests.post(f"{API}/auth/register",
                              json={"name": "T28 Reg", "email": email,
                                    "password": os.environ.get("TEST_USER_PASSWORD", "veryStrongPass123"),
                                    "phone": "+5359000999"})
            assert r.status_code in (200, 201), r.text
            u = db.users.find_one({"email": email})
            # If this happens to be the first user, role=admin and status=active.
            # Otherwise: status=under_review.
            if u["role"] in ("admin", "employee"):
                assert u["account_status"] == "active"
            else:
                assert u["account_status"] == "under_review"
        finally:
            db.users.delete_many({"email": email})
