"""iter55.37 — Session TTL security policy: hard cap at 24 hours.

Financial platform requirement: session tokens must not persist beyond 24h,
regardless of the auth path used (Google OAuth, email login, Emergent OAuth
bridge) or what the caller requests.

Tests:
  1. Email login without `remember_hours` → session lasts ~24h (was 168h/7d).
  2. Email login WITH `remember_hours=168` → clamped to 24h (attempts to
     over-request are silently capped, not rejected — keeps legacy clients
     working while enforcing the policy).
  3. Email login WITH `remember_hours=6` (below cap) → respects 6h.
  4. Cookie `Max-Age` header reflects the same clamped value.
"""
import os
import re
from datetime import datetime, timezone
from urllib.parse import unquote

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, TEST_USER_PASSWORD

API = f"{API_ROOT}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _login_email(email: str, password: str, remember_hours=None):
    """POST /auth/login with an optional remember_hours."""
    payload = {"email": email, "password": password}
    if remember_hours is not None:
        payload["remember_hours"] = remember_hours
    return requests.post(
        f"{API}/auth/login",
        json=payload,
        allow_redirects=False,
    )


def _seed_verified_user(email: str, password_hash: str):
    """Plant a phone-verified user we can login against."""
    db = _db()
    db.users.delete_many({"email": email})
    from uuid import uuid4
    db.users.insert_one({
        "user_id": f"test_ttl_{uuid4().hex[:8]}",
        "email": email,
        "name": "TTL Test",
        "role": "normal",
        "phone_verified": True,
        "account_status": "active",
        "password_hash": password_hash,
        "auth_provider": "email",
    })


def _hash(pw: str) -> str:
    """Match backend's bcrypt hash format so /auth/email/login succeeds."""
    import bcrypt
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _cookie_max_age(headers) -> int:
    """Extract Max-Age from Set-Cookie header — the source of truth the
    browser honors."""
    sc = headers.get("set-cookie", "")
    m = re.search(r"[Mm]ax-[Aa]ge=(\d+)", sc)
    return int(m.group(1)) if m else -1


def test_email_login_default_ttl_is_24h():
    """Without remember_hours, the session must last 24h (not the legacy 7d)."""
    email = "iter5537_default@ex.com"
    password = TEST_USER_PASSWORD
    _seed_verified_user(email, _hash(password))

    r = _login_email(email, password)
    assert r.status_code == 200, r.text
    max_age = _cookie_max_age(r.headers)
    assert max_age == 24 * 3600, (
        f"Default session cookie Max-Age = {max_age}s; expected {24*3600}s (24h)"
    )

    # DB expires_at must be ~24h from now
    from datetime import timedelta
    session = _db().user_sessions.find_one(
        {"session_token": {"$regex": ".+"}},
        sort=[("created_at", -1)],
    )
    expires = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(hours=23, minutes=59) < delta < timedelta(hours=24, minutes=1), (
        f"DB expires_at delta = {delta}; expected ~24h"
    )
    _db().users.delete_many({"email": email})


def test_email_login_over_request_is_clamped_to_24h():
    """A client requesting remember_hours=168 must still get 24h, not 168h."""
    email = "iter5537_clamp@ex.com"
    password = TEST_USER_PASSWORD
    _seed_verified_user(email, _hash(password))

    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "remember_hours": 168},
        allow_redirects=False,
    )
    assert r.status_code == 200, r.text
    max_age = _cookie_max_age(r.headers)
    assert max_age == 24 * 3600, (
        f"Session cookie Max-Age = {max_age}s when client asked for 168h — "
        f"MUST be clamped to 86400s (24h)"
    )
    _db().users.delete_many({"email": email})


def test_email_login_under_request_is_respected():
    """Requesting a SHORTER TTL (e.g. 6h) must be honored, not padded up."""
    email = "iter5537_short@ex.com"
    password = TEST_USER_PASSWORD
    _seed_verified_user(email, _hash(password))

    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "remember_hours": 6},
        allow_redirects=False,
    )
    assert r.status_code == 200, r.text
    max_age = _cookie_max_age(r.headers)
    assert max_age == 6 * 3600, (
        f"Session cookie Max-Age = {max_age}s when client asked for 6h; expected {6*3600}s"
    )
    _db().users.delete_many({"email": email})


def test_session_max_hours_constant():
    """Unit — the constant itself is 24 (regression guard against future edits)."""
    from auth_utils import SESSION_MAX_HOURS
    assert SESSION_MAX_HOURS == 24, (
        f"SESSION_MAX_HOURS = {SESSION_MAX_HOURS}; policy requires 24"
    )
