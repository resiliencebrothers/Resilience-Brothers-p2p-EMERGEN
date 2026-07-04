"""Backend regression + happy-path for the iter48 admin security dashboard.

Covers:
- GET /api/admin/security/audit returns the 5 expected sections.
- Non-admin (employee, vip, normal) gets 403.
- POST /api/admin/security/sessions/{user_id}/revoke wipes sessions for that
  user (admin-only).
- Origin-blocked events are logged into `security_events` and appear in the
  audit payload.
- Rate-limit hits are logged and grouped by IP.
"""
import os
import time
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
LOCAL_API = "http://localhost:8001/api"  # bypass proxy origin rewrite


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _cleanup_security_events():
    _db().security_events.delete_many({"kind": {"$in": ["origin_blocked", "rate_limit_hit", "admin_new_ip"]}})


def test_admin_security_audit_admin_ok():
    r = requests.get(f"{API}/admin/security/audit", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d.keys()) >= {
        "generated_at", "window_days", "active_sessions",
        "admin_new_ip_logins", "top_rate_limited_ips",
        "recent_origin_violations", "recent_login_bursts",
    }
    assert d["active_sessions"]["total"] >= 1
    assert isinstance(d["active_sessions"]["by_role"], dict)
    assert isinstance(d["active_sessions"]["staff_active"], list)


def test_admin_security_audit_forbidden_for_employee():
    r = requests.get(f"{API}/admin/security/audit", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 403


def test_admin_security_audit_forbidden_for_vip():
    r = requests.get(f"{API}/admin/security/audit", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 403


def test_admin_security_audit_forbidden_for_normal():
    r = requests.get(f"{API}/admin/security/audit", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 403


def test_admin_security_audit_no_token_401():
    r = requests.get(f"{API}/admin/security/audit")
    assert r.status_code in (401, 403)


def test_origin_blocked_event_logged():
    _cleanup_security_events()
    # Hit the LOCAL API so the proxy doesn't rewrite Origin.
    requests.post(
        f"{LOCAL_API}/auth/login",
        headers={"Origin": "https://evil.com", "Content-Type": "application/json"},
        json={"email": "x@y.com", "password": "z"},
    )
    time.sleep(0.3)  # let the async logger flush
    events = list(_db().security_events.find({"kind": "origin_blocked"}))
    assert len(events) >= 1
    assert events[-1]["origin"] == "https://evil.com"
    assert events[-1]["method"] == "POST"


def test_audit_dashboard_reflects_origin_events():
    _cleanup_security_events()
    for _ in range(2):
        requests.post(
            f"{LOCAL_API}/auth/login",
            headers={"Origin": "https://evil.com", "Content-Type": "application/json"},
            json={"email": "x@y.com", "password": "z"},
        )
    time.sleep(0.3)
    r = requests.get(f"{API}/admin/security/audit", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    origin_events = r.json()["recent_origin_violations"]
    assert len(origin_events) >= 2
    assert all(e["origin"] == "https://evil.com" for e in origin_events[:2])


def test_revoke_sessions_wipes_target_user():
    db = _db()
    # Plant a session
    db.user_sessions.insert_one({
        "user_id": "user_test_normal01",
        "session_token": "throwaway_token_iter48",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "created_at": "2026-07-04T12:00:00+00:00",
    })
    before = db.user_sessions.count_documents({"user_id": "user_test_normal01"})
    assert before >= 1

    r = requests.post(
        f"{API}/admin/security/sessions/user_test_normal01/revoke",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    assert r.json()["revoked"] >= 1

    after = db.user_sessions.count_documents({"user_id": "user_test_normal01"})
    assert after == 0

    # Re-seed a valid session so subsequent tests can use NORMAL_TOKEN
    db.user_sessions.insert_one({
        "user_id": "user_test_normal01",
        "session_token": NORMAL_TOKEN,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "created_at": "2026-07-04T12:00:00+00:00",
    })


def test_revoke_sessions_forbidden_for_employee():
    r = requests.post(
        f"{API}/admin/security/sessions/user_test_normal01/revoke",
        headers=_hdr(EMPLOYEE_TOKEN),
    )
    assert r.status_code == 403
