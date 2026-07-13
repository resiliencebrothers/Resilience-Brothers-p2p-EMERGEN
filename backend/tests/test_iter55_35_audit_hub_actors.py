"""iter55.35 — Global audit hub + actor autocomplete + deep-link.

Adds:
  - `GET /api/admin/audit/actors?q=&limit=` — distinct staff actors ordered
    by most-recent activity, filtered by name/email/user_id substring.
    Powers the "Por usuario" tab in the new `AdminAuditHub`.
  - Admin-only gate (uses `require_admin`, no separate permission).
"""
import os
import uuid
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, ADMIN_TOKEN

from tests.test_iter55_33_user_admin_gating import _setup_gated_staff, _cleanup, STAFF_TOKEN

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


PLANTED = []


def _plant(actor_id, name, email, role, minutes_ago=0):
    eid = str(uuid.uuid4())
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    _db().audit_log.insert_one({
        "id": eid, "actor_id": actor_id, "actor_name": name,
        "actor_email": email, "actor_role": role, "actor_permissions": [],
        "action": "test.audit_hub", "entity_type": "test", "entity_id": "x",
        "summary": f"test action by {name}", "details": {},
        "created_at": created_at,
    })
    PLANTED.append(eid)


def _cleanup_planted():
    if PLANTED:
        _db().audit_log.delete_many({"id": {"$in": PLANTED}})
        PLANTED.clear()


# ============================================================
# Access + shape
# ============================================================

def test_actors_endpoint_requires_admin():
    """Only admin can list actors (uses require_admin, no permission grant
    would help for gated staff)."""
    _setup_gated_staff(["users", "user_stats"])  # even with user_stats, blocked
    try:
        r = requests.get(f"{API}/admin/audit/actors", headers=_hdr(STAFF_TOKEN))
        assert r.status_code == 403, r.text
    finally:
        _cleanup()


def test_actors_endpoint_returns_shape():
    r = requests.get(f"{API}/admin/audit/actors?limit=3", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        r0 = rows[0]
        for k in ("actor_id", "actor_name", "actor_email", "actor_role",
                  "last_seen", "count"):
            assert k in r0


# ============================================================
# Filtering + ordering
# ============================================================

def test_actors_endpoint_matches_partial_name():
    """Substring match against actor_name is case-insensitive."""
    _cleanup_planted()
    tag = uuid.uuid4().hex[:6]
    _plant(f"actor_hub_{tag}", f"HubTest {tag}", f"hub.{tag}@resilience.com",
             "employee", minutes_ago=1)
    try:
        r = requests.get(
            f"{API}/admin/audit/actors?q={tag.upper()}&limit=10",
            headers=_hdr(ADMIN_TOKEN),
        )
        assert r.status_code == 200
        rows = r.json()
        assert any(row["actor_name"].endswith(tag) for row in rows), rows
    finally:
        _cleanup_planted()


def test_actors_endpoint_sort_by_last_seen_desc():
    """Actor with most recent activity comes first."""
    _cleanup_planted()
    older_id = f"actor_older_{uuid.uuid4().hex[:6]}"
    newer_id = f"actor_newer_{uuid.uuid4().hex[:6]}"
    _plant(older_id, "OlderActor", "older@rb.com", "employee", minutes_ago=1000)
    _plant(newer_id, "NewerActor", "newer@rb.com", "employee", minutes_ago=1)
    try:
        r = requests.get(
            f"{API}/admin/audit/actors?q=actor_&limit=100",
            headers=_hdr(ADMIN_TOKEN),
        )
        rows = r.json()
        newer_idx = next((i for i, r in enumerate(rows) if r["actor_id"] == newer_id), -1)
        older_idx = next((i for i, r in enumerate(rows) if r["actor_id"] == older_id), -1)
        # Both must be present and newer_idx < older_idx (comes first)
        assert newer_idx >= 0
        assert older_idx >= 0
        assert newer_idx < older_idx
    finally:
        _cleanup_planted()


def test_actors_endpoint_returns_count_per_actor():
    _cleanup_planted()
    aid = f"actor_count_{uuid.uuid4().hex[:6]}"
    for i in range(3):
        _plant(aid, "CountTest", "count@rb.com", "admin", minutes_ago=i)
    try:
        r = requests.get(
            f"{API}/admin/audit/actors?q=count_",
            headers=_hdr(ADMIN_TOKEN),
        )
        rows = r.json()
        target = next((r for r in rows if r["actor_id"] == aid), None)
        assert target is not None
        assert target["count"] >= 3
    finally:
        _cleanup_planted()


def test_actors_endpoint_limit_clamped():
    """`limit=99999` must be clamped to 100."""
    r = requests.get(f"{API}/admin/audit/actors?limit=99999",
                       headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    assert len(r.json()) <= 100
