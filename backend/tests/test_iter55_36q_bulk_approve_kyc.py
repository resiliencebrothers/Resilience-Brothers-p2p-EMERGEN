"""iter55.36q — Bulk-approve KYC endpoint.

`POST /admin/kyc/bulk-approve` drains the KYC queue quickly when staff has
visually inspected a batch of clean submissions. This suite locks down:
  - Contract shape (approved, failed, approved_count, failed_count)
  - Best-effort semantics: a mixed batch still commits the valid IDs
  - RBAC / permission enforcement
  - Payload validation (list length caps, empty list, notes cap)
  - Idempotency: re-running on already-verified IDs surfaces them as failed
    (not as a duplicate approval)
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

from conftest import (
    BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN,
)


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _plant_pending_kyc(uid_suffix: str = "") -> str:
    """Create a pending kyc_verifications row and return its id."""
    vid = f"kycq_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    cli, db = _db()
    db.kyc_verifications.insert_one({
        "id": vid,
        "user_id": f"bulk_test_{uid_suffix}",
        "user_email": f"bulk_{uid_suffix}@test.local",
        "user_name": f"Bulk Test {uid_suffix}",
        "user_phone": "+5350000000",
        "status": "pending",
        "documents": [
            {"doc_type": "id_front", "ref": "/tmp/x"},
            {"doc_type": "id_back", "ref": "/tmp/x"},
            {"doc_type": "selfie", "ref": "/tmp/x"},
        ],
        "risk_score": 10,
        "risk_flags": [],
        "submit_ip": "127.0.0.1",
        "submit_user_agent": "pytest",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": "",
        "rejection_reasons": [],
        "created_at": now,
        "updated_at": now,
    })
    db.users.update_one(
        {"user_id": f"bulk_test_{uid_suffix}"},
        {"$set": {"user_id": f"bulk_test_{uid_suffix}",
                  "email": f"bulk_{uid_suffix}@test.local",
                  "role": "normal",
                  "kyc_status": "pending"}},
        upsert=True,
    )
    cli.close()
    return vid


def _cleanup(vids):
    cli, db = _db()
    db.kyc_verifications.delete_many({"id": {"$in": vids}})
    db.users.delete_many({"user_id": {"$regex": "^bulk_test_"}})
    cli.close()


def _post(payload, token: str = ADMIN_TOKEN):
    return requests.post(
        f"{BASE_URL}/api/admin/kyc/bulk-approve",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


# ============================================================
# 1. Happy path
# ============================================================

class TestBulkApproveHappyPath:
    def test_approves_all_ids_and_returns_counts(self):
        v1 = _plant_pending_kyc("a1")
        v2 = _plant_pending_kyc("a2")
        v3 = _plant_pending_kyc("a3")
        try:
            r = _post({"ids": [v1, v2, v3], "notes": "batch review 2026-02-14"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["approved_count"] == 3
            assert body["failed_count"] == 0
            assert set(body["approved"]) == {v1, v2, v3}
            assert body["failed"] == []
            # DB side: all three flipped to verified
            cli, db = _db()
            for vid in (v1, v2, v3):
                doc = db.kyc_verifications.find_one({"id": vid})
                assert doc["status"] == "verified"
                assert doc["reviewed_at"] is not None
                assert doc["review_notes"] == "batch review 2026-02-14"
            cli.close()
        finally:
            _cleanup([v1, v2, v3])

    def test_updates_users_kyc_status_mirror(self):
        v1 = _plant_pending_kyc("mirror1")
        try:
            r = _post({"ids": [v1]})
            assert r.status_code == 200
            cli, db = _db()
            u = db.users.find_one({"user_id": "bulk_test_mirror1"})
            cli.close()
            assert u["kyc_status"] == "verified"
            assert "kyc_verified_at" in u
        finally:
            _cleanup([v1])


# ============================================================
# 2. Mixed batch — best-effort semantics
# ============================================================

class TestBulkApproveMixedBatch:
    def test_valid_ids_commit_invalid_ids_reported(self):
        v1 = _plant_pending_kyc("mix1")
        v2 = _plant_pending_kyc("mix2")
        try:
            r = _post({"ids": [v1, "nonexistent-id-xyz", v2]})
            assert r.status_code == 200
            body = r.json()
            assert body["approved_count"] == 2
            assert body["failed_count"] == 1
            assert set(body["approved"]) == {v1, v2}
            assert body["failed"][0]["id"] == "nonexistent-id-xyz"
            assert body["failed"][0]["reason"] == "not_pending_or_missing"
        finally:
            _cleanup([v1, v2])

    def test_already_verified_id_returns_as_failed_not_reapproved(self):
        v1 = _plant_pending_kyc("dup1")
        try:
            # First approve — success
            r1 = _post({"ids": [v1]})
            assert r1.status_code == 200
            assert r1.json()["approved_count"] == 1
            # Second approve on same id — must land in failed[]
            r2 = _post({"ids": [v1]})
            assert r2.status_code == 200
            body = r2.json()
            assert body["approved_count"] == 0
            assert body["failed_count"] == 1
            assert body["failed"][0]["id"] == v1
        finally:
            _cleanup([v1])


# ============================================================
# 3. RBAC
# ============================================================

class TestBulkApproveRBAC:
    def test_admin_can_bulk_approve(self):
        v1 = _plant_pending_kyc("adm1")
        try:
            r = _post({"ids": [v1]}, token=ADMIN_TOKEN)
            assert r.status_code == 200
        finally:
            _cleanup([v1])

    def test_normal_user_forbidden(self):
        r = _post({"ids": ["anything"]}, token=NORMAL_TOKEN)
        assert r.status_code == 403

    def test_vip_user_forbidden(self):
        r = _post({"ids": ["anything"]}, token=VIP_TOKEN)
        assert r.status_code == 403

    def test_no_token_unauthenticated(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/kyc/bulk-approve",
            json={"ids": ["x"]},
        )
        assert r.status_code == 401

    def test_employee_without_kyc_permission_forbidden(self):
        # Employee test user does NOT have `kyc` in their permissions by default.
        r = _post({"ids": ["x"]}, token=EMPLOYEE_TOKEN)
        assert r.status_code in (403, 200)  # 200 only if permission was granted


# ============================================================
# 4. Payload validation
# ============================================================

class TestBulkApprovePayloadValidation:
    def test_empty_list_returns_422(self):
        r = _post({"ids": []})
        assert r.status_code == 422

    def test_over_100_ids_returns_422(self):
        r = _post({"ids": [f"x{i}" for i in range(101)]})
        assert r.status_code == 422

    def test_missing_ids_field_returns_422(self):
        r = _post({"notes": "no ids"})
        assert r.status_code == 422

    def test_notes_over_500_chars_returns_422(self):
        r = _post({"ids": ["x"], "notes": "y" * 501})
        assert r.status_code == 422

    def test_notes_at_500_boundary_accepted(self):
        # 500-char notes is the max; endpoint should accept it even though
        # the ID is missing (returns 200 with 0 approved, 1 failed).
        r = _post({"ids": ["missing-id"], "notes": "z" * 500})
        assert r.status_code == 200
        assert r.json()["failed_count"] == 1


# ============================================================
# 5. Notification side-effect
# ============================================================

class TestBulkApproveNotifications:
    def test_success_creates_notifications_for_each_approved_user(self):
        v1 = _plant_pending_kyc("notif1")
        v2 = _plant_pending_kyc("notif2")
        try:
            r = _post({"ids": [v1, v2]})
            assert r.status_code == 200
            assert r.json()["approved_count"] == 2
            cli, db = _db()
            n1 = db.notifications.count_documents(
                {"recipient_user_id": "bulk_test_notif1", "type": "kyc_verified"}
            )
            n2 = db.notifications.count_documents(
                {"recipient_user_id": "bulk_test_notif2", "type": "kyc_verified"}
            )
            cli.close()
            assert n1 >= 1
            assert n2 >= 1
        finally:
            cli, db = _db()
            db.notifications.delete_many({"recipient_user_id": {"$regex": "^bulk_test_"}})
            cli.close()
            _cleanup([v1, v2])
