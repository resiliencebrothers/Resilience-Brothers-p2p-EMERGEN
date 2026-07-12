"""iter55.37 regression — Session-TTL 24h cap: additional coverage.

Covers items requested by main agent that were NOT in
test_iter55_37_session_ttl_24h.py:

  1. DB `expires_at` for the CLAMPED case (remember_hours=168) is ~24h.
  2. DB `expires_at` for the UNDER case (remember_hours=6) is ~6h.
  3. /api/auth/me is authorized while token valid.
  4. /api/auth/logout clears the cookie and invalidates the session.
  5. A session whose DB expires_at is in the past → /api/auth/me returns 401.
  6. Legacy Emergent OAuth bridge path (`POST /api/auth/session`) uses
     the same 24h TTL — verified via unit test of `_create_session`
     because hitting the actual Emergent demobackend requires a real
     session_id we cannot mint from a test harness.
"""
import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import bcrypt
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT

API = f"{API_ROOT}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _seed_verified_user(email: str, password_hash: str) -> str:
    db = _db()
    db.users.delete_many({"email": email})
    uid = f"test_ttlreg_{uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid,
        "email": email,
        "name": "TTL Regression",
        "role": "normal",
        "phone_verified": True,
        "account_status": "active",
        "password_hash": password_hash,
        "auth_provider": "email",
    })
    return uid


def _cookie_max_age(headers) -> int:
    sc = headers.get("set-cookie", "")
    m = re.search(r"[Mm]ax-[Aa]ge=(\d+)", sc)
    return int(m.group(1)) if m else -1


def _session_token_from(headers) -> str:
    sc = headers.get("set-cookie", "")
    m = re.search(r"session_token=([a-f0-9]+)", sc)
    return m.group(1) if m else ""


def _login(email, password, remember_hours=None):
    body = {"email": email, "password": password}
    if remember_hours is not None:
        body["remember_hours"] = remember_hours
    return requests.post(f"{API}/auth/login", json=body, allow_redirects=False)


# ---------- DB expires_at parity for clamp / under cases ----------

def test_db_expires_at_matches_clamped_ttl_for_over_request():
    email = f"iter5537_reg_clamp_{uuid4().hex[:6]}@ex.com"
    password = "TestPass123!"
    _seed_verified_user(email, _hash(password))

    r = _login(email, password, remember_hours=168)
    assert r.status_code == 200, r.text
    max_age = _cookie_max_age(r.headers)
    assert max_age == 24 * 3600

    token = _session_token_from(r.headers)
    assert token, "session_token cookie missing"
    sess = _db().user_sessions.find_one({"session_token": token})
    assert sess is not None, "session not persisted in DB"
    created = datetime.fromisoformat(sess["created_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(sess["expires_at"].replace("Z", "+00:00"))
    delta = expires - created
    assert timedelta(hours=23, minutes=59) <= delta <= timedelta(hours=24, minutes=1), (
        f"DB expires_at delta = {delta}; expected ~24h (clamped)"
    )
    _db().users.delete_many({"email": email})
    _db().user_sessions.delete_many({"session_token": token})


def test_db_expires_at_matches_under_request_6h():
    email = f"iter5537_reg_under_{uuid4().hex[:6]}@ex.com"
    password = "TestPass123!"
    _seed_verified_user(email, _hash(password))

    r = _login(email, password, remember_hours=6)
    assert r.status_code == 200, r.text
    assert _cookie_max_age(r.headers) == 6 * 3600

    token = _session_token_from(r.headers)
    sess = _db().user_sessions.find_one({"session_token": token})
    created = datetime.fromisoformat(sess["created_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(sess["expires_at"].replace("Z", "+00:00"))
    delta = expires - created
    assert timedelta(hours=5, minutes=59) <= delta <= timedelta(hours=6, minutes=1), (
        f"DB expires_at delta = {delta}; expected ~6h"
    )
    _db().users.delete_many({"email": email})
    _db().user_sessions.delete_many({"session_token": token})


# ---------- /auth/me works while token valid ----------

def test_me_authorized_with_fresh_login_token():
    email = f"iter5537_reg_me_{uuid4().hex[:6]}@ex.com"
    password = "TestPass123!"
    _seed_verified_user(email, _hash(password))

    r = _login(email, password)
    token = _session_token_from(r.headers)
    assert token

    r2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    assert r2.json().get("email") == email
    _db().users.delete_many({"email": email})
    _db().user_sessions.delete_many({"session_token": token})


# ---------- /auth/logout removes cookie AND invalidates session ----------

def test_logout_invalidates_session_and_me_returns_401():
    email = f"iter5537_reg_logout_{uuid4().hex[:6]}@ex.com"
    password = "TestPass123!"
    _seed_verified_user(email, _hash(password))

    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    token = s.cookies.get("session_token")
    assert token, "session_token cookie not stored in session"

    # /auth/me works before logout
    r_me1 = s.get(f"{API}/auth/me")
    assert r_me1.status_code == 200

    # POST /auth/logout
    r_out = s.post(f"{API}/auth/logout")
    assert r_out.status_code == 200
    assert r_out.json().get("ok") is True

    # Set-Cookie header on logout should clear session_token
    sc = r_out.headers.get("set-cookie", "")
    # Cookie should be cleared — presence of expires=Thu, 01 Jan 1970 or Max-Age=0
    assert "session_token=" in sc
    cleared = ("Max-Age=0" in sc) or ("expires=Thu, 01 Jan 1970" in sc) or ("Expires=Thu, 01 Jan 1970" in sc)
    assert cleared, f"Logout did not clear session_token cookie. set-cookie={sc}"

    # Server-side: session row removed from DB
    assert _db().user_sessions.find_one({"session_token": token}) is None

    # /auth/me with the old bearer must now 401
    r_me2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r_me2.status_code == 401, r_me2.text

    _db().users.delete_many({"email": email})


# ---------- Expired session → 401 ----------

def test_expired_session_is_rejected():
    """A session_token whose expires_at is in the past must not authenticate,
    regardless of the (frontend) cookie Max-Age."""
    email = f"iter5537_reg_exp_{uuid4().hex[:6]}@ex.com"
    password = "TestPass123!"
    _seed_verified_user(email, _hash(password))

    r = _login(email, password)
    token = _session_token_from(r.headers)
    assert token

    # Force expiry 1h in the past
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _db().user_sessions.update_one(
        {"session_token": token}, {"$set": {"expires_at": past}}
    )

    r_me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r_me.status_code == 401, r_me.text

    _db().users.delete_many({"email": email})
    _db().user_sessions.delete_many({"session_token": token})


# ---------- Unit-level: _create_session applies 24h cap uniformly ----------

def test_create_session_clamps_to_24h_regardless_of_caller():
    """Simulates the legacy `POST /auth/session` bridge and Google callback:
    both call `_create_session` — the helper must clamp any request > 24h
    to exactly 24h (86400 seconds max-age)."""
    import sys
    sys.path.insert(0, "/app/backend")
    from auth_utils import _create_session, SESSION_MAX_HOURS
    from fastapi import Response

    assert SESSION_MAX_HOURS == 24

    async def _all():
        results = []
        uids = []
        for hours in (168, 3, 0):
            resp = Response()
            uid = f"test_unit_{uuid4().hex[:8]}"
            uids.append(uid)
            await _create_session(uid, resp, ttl_hours=hours)
            sc = resp.headers.get("set-cookie", "")
            m = re.search(r"[Mm]ax-[Aa]ge=(\d+)", sc)
            results.append((hours, int(m.group(1)) if m else -1, sc))
        return results, uids

    results, uids = asyncio.run(_all())
    # Over-request → clamped to 24h
    assert results[0][1] == 24 * 3600, results[0]
    # Under-request → respected
    assert results[1][1] == 3 * 3600, results[1]
    # Zero / negative → floored to 1h
    assert results[2][1] == 1 * 3600, results[2]
    for uid in uids:
        _db().user_sessions.delete_many({"user_id": uid})
