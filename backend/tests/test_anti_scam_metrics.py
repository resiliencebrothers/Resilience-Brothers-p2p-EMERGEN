"""iter46 — anti-scam analytics in the Admin Health dashboard.

Tests the lifecycle helpers (mark_user_under_review, mark_user_active) and
the aggregate `compute_anti_scam_metrics` exposed through
GET /api/admin/health/summary as the `anti_scam` section.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

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


def _iso(dt):
    return dt.isoformat()


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def synthetic_users():
    """Insert a small fixture of users in known states, then clean up."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    ids = []

    def _add(**fields):
        uid = f"test_antiscam_{uuid.uuid4().hex[:8]}"
        ids.append(uid)
        db.users.insert_one({
            "user_id": uid,
            "email": f"{uid}@example.com",
            "name": "AS Test", "role": "normal",
            "phone": "+5350000000", "phone_verified": False,
            "vip_balance_usd": 0.0,
            "created_at": _iso(_now()),
            **fields,
        })
        return uid

    # 2 pending under_review tickets stamped 5h and 30h ago
    pending_recent = _add(
        account_status="under_review",
        under_review_since=_iso(_now() - timedelta(hours=5)),
    )
    pending_old = _add(
        account_status="under_review",
        under_review_since=_iso(_now() - timedelta(hours=30)),
    )
    # 3 resolved cases with known durations: 1, 5, 12 hours → avg 6
    resolved_1 = _add(
        account_status="active", phone_verified=True, last_under_review_hours=1.0,
    )
    resolved_5 = _add(
        account_status="active", phone_verified=True, last_under_review_hours=5.0,
    )
    resolved_12 = _add(
        account_status="active", phone_verified=True, last_under_review_hours=12.0,
    )
    yield {
        "pending": [pending_recent, pending_old],
        "resolved": [resolved_1, resolved_5, resolved_12],
        "all": ids,
    }
    db.users.delete_many({"user_id": {"$in": ids}})


class TestAntiScamMetrics:
    def test_health_endpoint_includes_anti_scam_section(self, synthetic_users):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary",
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "anti_scam" in body, list(body.keys())
        a = body["anti_scam"]
        # No error wrapper
        assert "error" not in a, a
        assert {"users_under_review", "avg_resolution_hours",
                "resolved_count", "oldest_pending_hours"} <= set(a.keys())

    def test_queue_depth_counts_under_review_users(self, synthetic_users):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary",
                         headers=_h(ADMIN_TOKEN))
        a = r.json()["anti_scam"]
        # at least our 2 synthetic pending ones — others may exist
        assert a["users_under_review"] >= 2

    def test_avg_resolution_hours_includes_synthetic_cases(self, synthetic_users):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary",
                         headers=_h(ADMIN_TOKEN))
        a = r.json()["anti_scam"]
        # Our 3 resolved cases contribute 1, 5, 12 (avg 6). Combined with any
        # pre-existing rows, the overall avg must still be > 0 and resolved
        # count must include ours.
        assert a["resolved_count"] >= 3
        assert a["avg_resolution_hours"] is not None
        assert a["avg_resolution_hours"] > 0

    def test_oldest_pending_hours_reflects_our_30h_ticket(self, synthetic_users):
        r = requests.get(f"{BASE_URL}/api/admin/health/summary",
                         headers=_h(ADMIN_TOKEN))
        a = r.json()["anti_scam"]
        # The 30h-old ticket is the floor — the metric is >= 30
        assert a["oldest_pending_hours"] is not None
        assert a["oldest_pending_hours"] >= 30


class TestMarkUserHelpers:
    """Integration tests via the HTTP endpoint that calls mark_user_active."""

    def test_verify_phone_stamps_last_under_review_hours(self):
        """POST /api/admin/users/.../verify-phone calls mark_user_active which
        must compute the elapsed hours and store them in
        `last_under_review_hours`. Goes end-to-end through TOTP step-up."""
        from conftest import make_admin_totp
        db = MongoClient(MONGO_URL)[DB_NAME]
        uid = f"test_mau_{uuid.uuid4().hex[:8]}"
        phone = f"+1555{uuid.uuid4().hex[:7]}"
        ten_hours_ago = _iso(_now() - timedelta(hours=10))
        db.users.insert_one({
            "user_id": uid, "email": f"{uid}@x.com", "name": "x",
            "role": "normal", "account_status": "under_review",
            "phone": phone, "phone_verified": False,
            "under_review_since": ten_hours_ago,
        })
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/users/{uid}/verify-phone",
                headers=_h(ADMIN_TOKEN),
                json={"totp_code": make_admin_totp()},
            )
            assert r.status_code == 200, r.text
            fresh = db.users.find_one({"user_id": uid}, {"_id": 0})
            assert fresh["account_status"] == "active"
            assert fresh["phone_verified"] is True
            assert "under_review_since" not in fresh
            hours = fresh["last_under_review_hours"]
            assert 9.5 <= hours <= 10.5, f"got {hours}"
        finally:
            db.users.delete_one({"user_id": uid})
