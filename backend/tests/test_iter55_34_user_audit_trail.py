"""iter55.34 — Per-user audit trail on stats page.

Operator ask (13 Feb 2026): show "quién del staff modificó qué al usuario"
inside the admin user stats page. Backend endpoint returns audit_log entries
touching this user, filtered by window (7/30/90 days) and gated by the same
`user_stats` permission as the enclosing page.
"""
import os
import uuid
import bcrypt
import pyotp
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, ADMIN_TOKEN

API = f"{API_ROOT}/api"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso():
    return datetime.now(timezone.utc).isoformat()


# Reuse the gated-staff fixture pattern from iter55.33
from tests.test_iter55_33_user_admin_gating import _setup_gated_staff, _cleanup, STAFF_TOKEN


TARGET_USER_ID = "user_test_audit_trail_target"
PLANTED_IDS = []


def _ensure_target_user():
    """Provision a dedicated dummy user that ONLY the audit-trail tests
    reference. Keeps other test data (which touches user_test_vip01) out
    of the query results so limit-clamping doesn't hide our plants."""
    _db().users.update_one(
        {"user_id": TARGET_USER_ID},
        {"$set": {
            "user_id": TARGET_USER_ID,
            "email": "audit.trail.dummy@resilience.example.com",
            "name": "Audit Trail Dummy",
            "role": "normal",
            "account_status": "active",
            "created_at": _iso(),
        }},
        upsert=True,
    )


def _remove_target_user():
    _db().users.delete_many({"user_id": TARGET_USER_ID})


def _plant(entity_type, entity_id, action, actor_name, summary, days_ago=0,
            details_user_id=None, actor_role="admin"):
    eid = str(uuid.uuid4())
    created_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    doc = {
        "id": eid,
        "actor_id": "test_actor_" + actor_name.replace(" ", "_").lower(),
        "actor_name": actor_name,
        "actor_email": f"{actor_name.replace(' ', '.').lower()}@resilience.com",
        "actor_role": actor_role,
        "actor_permissions": [],
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "summary": summary,
        "details": {"user_id": details_user_id} if details_user_id else {},
        "created_at": created_at,
    }
    _db().audit_log.insert_one(doc)
    PLANTED_IDS.append(eid)


def _cleanup_planted():
    if PLANTED_IDS:
        _db().audit_log.delete_many({"id": {"$in": PLANTED_IDS}})
        PLANTED_IDS.clear()


# ============================================================
# Access control
# ============================================================

def test_audit_trail_requires_user_stats_permission():
    """Staff with `['users']` but NOT `user_stats` → 403."""
    _ensure_target_user()
    _setup_gated_staff(["users"])
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail",
            headers=_hdr(STAFF_TOKEN),
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup()
        _remove_target_user()


def test_audit_trail_available_to_admin_and_gated_staff():
    """Admin: 200. Staff with `user_stats`: 200."""
    _ensure_target_user()
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail",
            headers=_hdr(ADMIN_TOKEN),
        )
        assert r.status_code == 200, r.text
        assert "entries" in r.json()

        _setup_gated_staff(["users", "user_stats"])
        try:
            r2 = requests.get(
                f"{API}/admin/users/{TARGET_USER_ID}/audit-trail",
                headers=_hdr(STAFF_TOKEN),
            )
            assert r2.status_code == 200, r2.text
        finally:
            _cleanup()
    finally:
        _remove_target_user()


def test_audit_trail_404_for_unknown_user():
    r = requests.get(
        f"{API}/admin/users/user_does_not_exist_xxx/audit-trail",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 404


# ============================================================
# Query semantics
# ============================================================

def test_audit_trail_returns_entries_matching_entity_id():
    """Direct user edits (entity_type='user', entity_id=<uid>) must appear."""
    _ensure_target_user()
    _cleanup_planted()
    _plant("user", TARGET_USER_ID, "user.update", "Admin Test",
             "Cambió el rol a VIP", days_ago=1)
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail?days=30",
            headers=_hdr(ADMIN_TOKEN),
        )
        assert r.status_code == 200
        entries = r.json()["entries"]
        planted_ids = [e["id"] for e in entries if e["id"] in PLANTED_IDS]
        assert len(planted_ids) == 1
    finally:
        _cleanup_planted()
        _remove_target_user()


def test_audit_trail_returns_entries_matching_details_user_id():
    """Actions where the user is affected through `details.user_id`
    (e.g. capital_request.approved) must also appear."""
    _ensure_target_user()
    _cleanup_planted()
    _plant("capital_request", "cr_test_xyz", "capital_request.approved",
             "Admin Test", "Aprobó 500 USDT",
             days_ago=2, details_user_id=TARGET_USER_ID)
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail?days=30",
            headers=_hdr(ADMIN_TOKEN),
        )
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert any(e["id"] in PLANTED_IDS for e in entries)
    finally:
        _cleanup_planted()
        _remove_target_user()


def test_audit_trail_window_filter_applied():
    """Entries older than the window are excluded."""
    _ensure_target_user()
    _cleanup_planted()
    _plant("user", TARGET_USER_ID, "user.update", "Admin Old",
             "hace 60 días", days_ago=60)
    _plant("user", TARGET_USER_ID, "user.update", "Admin Recent",
             "ayer", days_ago=1)
    try:
        # 30-day window → only the recent one
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail?days=30",
            headers=_hdr(ADMIN_TOKEN),
        )
        entries = r.json()["entries"]
        planted = [e for e in entries if e["id"] in PLANTED_IDS]
        assert len(planted) == 1
        assert planted[0]["actor_name"] == "Admin Recent"

        # 90-day window → both
        r2 = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail?days=90&limit=500",
            headers=_hdr(ADMIN_TOKEN),
        )
        planted2 = [e for e in r2.json()["entries"] if e["id"] in PLANTED_IDS]
        assert len(planted2) == 2
    finally:
        _cleanup_planted()
        _remove_target_user()


def test_audit_trail_sort_newest_first():
    _ensure_target_user()
    _cleanup_planted()
    _plant("user", TARGET_USER_ID, "user.update", "Admin A",
             "más viejo", days_ago=5)
    _plant("user", TARGET_USER_ID, "user.update", "Admin B",
             "más nuevo", days_ago=1)
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail?days=30",
            headers=_hdr(ADMIN_TOKEN),
        )
        planted = [e for e in r.json()["entries"] if e["id"] in PLANTED_IDS]
        assert len(planted) == 2
        # Newest first: Admin B should come before Admin A
        idx_b = next(i for i, e in enumerate(planted) if e["actor_name"] == "Admin B")
        idx_a = next(i for i, e in enumerate(planted) if e["actor_name"] == "Admin A")
        assert idx_b < idx_a
    finally:
        _cleanup_planted()
        _remove_target_user()


def test_audit_trail_limit_and_days_are_clamped():
    """Malicious `days=9999` and `limit=99999` must be clamped."""
    _ensure_target_user()
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail?days=9999&limit=99999",
            headers=_hdr(ADMIN_TOKEN),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["window_days"] <= 365
        assert len(body["entries"]) <= 500
    finally:
        _remove_target_user()


def test_audit_trail_response_structure():
    """Response has the expected keys used by the frontend."""
    _ensure_target_user()
    _cleanup_planted()
    _plant("user", TARGET_USER_ID, "user.update", "Admin Test", "test", days_ago=0)
    try:
        r = requests.get(
            f"{API}/admin/users/{TARGET_USER_ID}/audit-trail",
            headers=_hdr(ADMIN_TOKEN),
        )
        body = r.json()
        assert set(body.keys()) >= {"user_id", "window_days", "total", "entries"}
        # Verify the frontend-required fields on our own planted entry
        planted = [e for e in body["entries"] if e["id"] in PLANTED_IDS]
        assert planted
        for k in ("id", "created_at", "action", "actor_role"):
            assert k in planted[0]
    finally:
        _cleanup_planted()
        _remove_target_user()
