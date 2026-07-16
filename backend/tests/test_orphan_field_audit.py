"""Orphan-field audit — regression guard against endpoints that read from
MongoDB fields that don't exist (a.k.a. "phantom fields").

Historic offenders caught in production:
  - iter65: `/api/profile/me` was reading `twofa_enabled` while the real DB
    field is `totp_enabled`. Result: 2FA badge in the profile widget always
    showed "2FA NO CONFIGURADO" even for users with 2FA active.
  - iter65: `/api/admin/users/{id}` used `db.kyc` (empty collection) instead
    of `db.kyc_verifications`, projecting `submitted_at`/`reviewer_notes`
    (which don't exist) instead of `created_at`/`review_notes`.

Each test in this file:
  1. Seeds a KNOWN state on a test user (both the real field and the phantom
     field with OPPOSITE values, so a bug is trivially visible).
  2. Hits the API endpoint.
  3. Asserts the response mirrors the REAL DB field, not the phantom one.

If any of these tests fail, the endpoint is likely reading from the wrong
field name — check the recent commits for a typo or unfinished rename.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN,
)

API = f"{BASE_URL}/api"


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _restore_vip_kyc():
    """Ensure the VIP test user has a verified KYC row (needed by many other
    suites); tests here may temporarily flip states."""
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    db.kyc_verifications.update_one(
        {"user_id": "user_test_vip01", "id": "kyc_user_test_vip01"},
        {"$set": {
            "id": "kyc_user_test_vip01",
            "user_id": "user_test_vip01",
            "status": "verified",
            "created_at": now,
            "reviewed_at": now,
            "reviewed_by": "user_test_admin01",
            "review_notes": "orphan-audit re-seed",
            "documents": [],
        }},
        upsert=True,
    )


# ============================================================
# /api/profile/me — user self-service view
# ============================================================

def test_profile_me_twofa_enabled_reads_totp_enabled_true():
    """When DB has totp_enabled=True, the response must be twofa_enabled=True.
    Guards against a rename that reads a phantom `twofa_enabled` column.
    """
    db = _db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        # Set the phantom field to the OPPOSITE — a bug that reads phantom
        # would return False, but the real field says True.
        {"$set": {"totp_enabled": True, "twofa_enabled": False}},
    )
    r = requests.get(f"{API}/profile/me", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["twofa_enabled"] is True, (
        "twofa_enabled must reflect the real DB `totp_enabled` field "
        "(True), not the phantom `twofa_enabled` field (False)."
    )


def test_profile_me_twofa_enabled_reads_totp_enabled_false():
    db = _db()
    db.users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"totp_enabled": False, "twofa_enabled": True}},
    )
    r = requests.get(f"{API}/profile/me", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["twofa_enabled"] is False, (
        "twofa_enabled must reflect the real DB `totp_enabled` (False), "
        "not the phantom `twofa_enabled` (True)."
    )
    # Restore for other tests
    db.users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"totp_enabled": True}, "$unset": {"twofa_enabled": ""}},
    )


def test_profile_me_kyc_status_reads_kyc_verifications_collection():
    """The KYC status must come from db.kyc_verifications (canonical),
    not from a phantom collection. Regression guard against admin_users.py
    which historically read from db.kyc (empty collection).
    """
    _restore_vip_kyc()
    r = requests.get(f"{API}/profile/me", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["kyc_status"] == "verified", (
        "kyc_status must come from db.kyc_verifications. If this returns "
        "'not_started' when the collection has a verified row, the endpoint "
        "is likely reading from the wrong collection."
    )


def test_profile_me_email_verified_reflects_db():
    db = _db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"email_verified": True}},
    )
    r = requests.get(f"{API}/profile/me", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200
    # /profile/me doesn't expose email_verified today — this test is a
    # placeholder for when it does (planned for the identity-audit sweep).
    # For now, just verify no error path.


# ============================================================
# /api/admin/users/{id} — staff view of any user
# ============================================================

def test_admin_user_detail_twofa_enabled_reads_totp_enabled():
    """Same phantom-field risk as /profile/me, but on the admin endpoint."""
    db = _db()
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"totp_enabled": True, "twofa_enabled": False}},
    )
    r = requests.get(f"{API}/admin/users/user_test_vip01/stats", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["user"]["twofa_enabled"] is True, (
        "admin/users/{id}/stats.user.twofa_enabled must reflect real DB "
        "`totp_enabled` (True), not phantom `twofa_enabled` (False)."
    )


def test_admin_user_detail_kyc_status_reads_kyc_verifications():
    """/api/admin/users/{id}/stats previously read `db.kyc` (empty collection).
    Ensure it now reads from `db.kyc_verifications` (canonical).
    """
    _restore_vip_kyc()
    r = requests.get(f"{API}/admin/users/user_test_vip01/stats", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    kyc = r.json()["kyc"]
    assert kyc["status"] == "verified", (
        "admin/users/{id}/stats.kyc.status must come from db.kyc_verifications "
        f"(got {kyc['status']!r}). If 'not_started' with a verified row "
        "seeded, the endpoint is likely reading from the wrong collection."
    )
    assert kyc["submitted_at"], (
        "submitted_at must be mapped from the real `created_at` field on "
        "kyc_verifications. Got empty string — check the phantom field name."
    )


def test_admin_user_detail_kyc_reviewer_notes_reads_review_notes():
    """kyc_verifications stores the field as `review_notes` (see
    services/kyc.py) — admin endpoint used to read `reviewer_notes` (phantom).
    """
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    db.kyc_verifications.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"review_notes": "orphan-audit-marker-42", "created_at": now,
                  "status": "verified"}},
        upsert=False,
    )
    r = requests.get(f"{API}/admin/users/user_test_vip01/stats", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["kyc"]["reviewer_notes"] == "orphan-audit-marker-42", (
        "admin/users/{id}/stats.kyc.reviewer_notes must reflect DB `review_notes` "
        "field, not the phantom `reviewer_notes` field."
    )
