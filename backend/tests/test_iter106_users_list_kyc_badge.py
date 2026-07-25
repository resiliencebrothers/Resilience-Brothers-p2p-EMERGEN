"""iter106 — GET /admin/users enriches each user with `effective_kyc_status`.

The admin user list badge must mirror the same fallback used by
/admin/users/:id/stats (fixed in iter55.35):
  1. If a `kyc_verifications` row exists → use its `status`.
  2. Else fall back to `users.kyc_status` (or "not_started").
  3. `unverified` is normalized to `not_started`.

Also verifies employee/admin users get the field too (they'll show "—" in UI
but the backend keeps its shape consistent).
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@pytest.fixture
def planted():
    db = MongoClient(MONGO_URL)[DB_NAME]
    ids = []
    kyc_ids = []

    def add_user(**fields):
        uid = f"test_kyc_{uuid.uuid4().hex[:8]}"
        ids.append(uid)
        db.users.insert_one({
            "user_id": uid, "email": f"{uid}@x.com", "name": f"KYC {uid[:4]}",
            "role": "normal", "account_status": "active",
            "phone_verified": True,
            **fields,
        })
        return uid

    def add_kyc(uid, status, ago_minutes=10):
        kid = f"kyc_{uuid.uuid4().hex[:8]}"
        kyc_ids.append(kid)
        db.kyc_verifications.insert_one({
            "id": kid, "user_id": uid, "user_email": f"{uid}@x.com",
            "user_name": "K", "user_phone": "",
            "status": status, "documents": [], "risk_score": 0,
            "risk_flags": [], "created_at":
                (datetime.now(timezone.utc) - timedelta(minutes=ago_minutes)).isoformat(),
        })
        return kid

    verified = add_user()
    add_kyc(verified, "verified")

    pending = add_user()
    add_kyc(pending, "pending")

    rejected = add_user()
    add_kyc(rejected, "rejected")

    # Two KYC rows — latest one wins (most recent by created_at).
    latest_wins = add_user()
    add_kyc(latest_wins, "rejected", ago_minutes=60)
    add_kyc(latest_wins, "verified", ago_minutes=5)

    # No KYC row + kyc_status on the user doc.
    user_status_only = add_user(kyc_status="verified")

    # No KYC row, no kyc_status → not_started default.
    fresh = add_user()

    # `unverified` on the user doc → normalized to not_started.
    unverified = add_user(kyc_status="unverified")

    # Staff still gets the field (UI hides it with "—").
    employee = add_user(role="employee")

    yield {
        "verified": verified, "pending": pending, "rejected": rejected,
        "latest_wins": latest_wins, "user_status_only": user_status_only,
        "fresh": fresh, "unverified": unverified, "employee": employee,
    }

    db.users.delete_many({"user_id": {"$in": ids}})
    db.kyc_verifications.delete_many({"id": {"$in": kyc_ids}})


class TestUsersListKycEnrichment:
    def _find(self, docs, uid):
        return next((d for d in docs if d.get("user_id") == uid), None)

    def _fetch_all(self):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers=_h(ADMIN_TOKEN), params={"limit": 1000})
        assert r.status_code == 200
        return r.json()

    def test_verified_from_kyc_collection(self, planted):
        d = self._find(self._fetch_all(), planted["verified"])
        assert d is not None
        assert d.get("effective_kyc_status") == "verified"

    def test_pending_from_kyc_collection(self, planted):
        d = self._find(self._fetch_all(), planted["pending"])
        assert d.get("effective_kyc_status") == "pending"

    def test_rejected_from_kyc_collection(self, planted):
        d = self._find(self._fetch_all(), planted["rejected"])
        assert d.get("effective_kyc_status") == "rejected"

    def test_latest_kyc_row_wins(self, planted):
        """Two rows: an old 'rejected' + a newer 'verified' → verified."""
        d = self._find(self._fetch_all(), planted["latest_wins"])
        assert d.get("effective_kyc_status") == "verified"

    def test_fallback_to_user_kyc_status(self, planted):
        d = self._find(self._fetch_all(), planted["user_status_only"])
        assert d.get("effective_kyc_status") == "verified"

    def test_default_not_started(self, planted):
        d = self._find(self._fetch_all(), planted["fresh"])
        assert d.get("effective_kyc_status") == "not_started"

    def test_unverified_is_normalized(self, planted):
        d = self._find(self._fetch_all(), planted["unverified"])
        assert d.get("effective_kyc_status") == "not_started"

    def test_staff_users_also_receive_field(self, planted):
        d = self._find(self._fetch_all(), planted["employee"])
        assert d is not None
        # Field is present so the frontend can safely read it.
        assert "effective_kyc_status" in d
        assert d["effective_kyc_status"] == "not_started"
