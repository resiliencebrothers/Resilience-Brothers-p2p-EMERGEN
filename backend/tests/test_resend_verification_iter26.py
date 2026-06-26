"""Backend tests for POST /api/auth/resend-verification (iter26).
Validates: generic 200 for nonexistent/verified/google; 200 + token regen +
last_resend_at for unverified password user; 429 rate-limit; 422 for bad email.
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                BASE_URL = line.split('=', 1)[1].strip().strip('"').rstrip('/')
                break

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"
GENERIC_MSG_FRAGMENT = "Si la cuenta existe"


def iso(dt): return dt.isoformat()
def now(): return datetime.now(timezone.utc)


@pytest.fixture
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _insert_user(db, *, verified=False, provider="password", last_resend=None):
    tok = uuid.uuid4().hex + uuid.uuid4().hex
    email = f"test_resend_{uuid.uuid4().hex[:8]}@example.com"
    doc = {
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "email": email,
        "name": "Resend Test User",
        "role": "normal",
        "auth_provider": provider,
        "password_hash": "fake_hash" if provider == "password" else None,
        "email_verified": verified,
        "created_at": iso(now()),
    }
    if provider == "password" and not verified:
        doc["verification_token"] = tok
        doc["verification_expires_at"] = iso(now() + timedelta(hours=24))
    if last_resend is not None:
        doc["last_resend_at"] = iso(last_resend)
    db.users.insert_one(doc)
    return doc


def _cleanup(db, user):
    db.users.delete_one({"user_id": user["user_id"]})


# ===== Nonexistent email -> 200 generic =====
def test_resend_nonexistent_email_returns_generic_200():
    fake_email = f"never_existed_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": fake_email}, timeout=15)
    assert r.status_code == 200, f"got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("ok") is True
    assert GENERIC_MSG_FRAGMENT in data.get("message", "")


# ===== Invalid email format -> 422 =====
def test_resend_invalid_email_format_returns_422():
    r = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": "not-an-email"}, timeout=15)
    assert r.status_code == 422, f"got {r.status_code}: {r.text}"


# ===== Already verified user -> 200 generic, no DB changes =====
def test_resend_already_verified_returns_generic_no_changes(db):
    user = _insert_user(db, verified=True)
    try:
        before = db.users.find_one({"user_id": user["user_id"]})
        r = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": user["email"]}, timeout=15)
        assert r.status_code == 200
        assert GENERIC_MSG_FRAGMENT in r.json().get("message", "")
        after = db.users.find_one({"user_id": user["user_id"]})
        assert after.get("last_resend_at") == before.get("last_resend_at")  # both None
        assert "verification_token" not in after
    finally:
        _cleanup(db, user)


# ===== Google account -> 200 generic, no DB changes =====
def test_resend_google_account_returns_generic_no_changes(db):
    user = _insert_user(db, verified=True, provider="google")
    try:
        before = db.users.find_one({"user_id": user["user_id"]})
        r = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": user["email"]}, timeout=15)
        assert r.status_code == 200
        assert GENERIC_MSG_FRAGMENT in r.json().get("message", "")
        after = db.users.find_one({"user_id": user["user_id"]})
        assert after.get("last_resend_at") == before.get("last_resend_at")
        assert "verification_token" not in after
    finally:
        _cleanup(db, user)


# ===== Unverified password user -> 200, token regen, last_resend_at set =====
def test_resend_unverified_user_regenerates_token(db):
    user = _insert_user(db, verified=False)
    old_token = user["verification_token"]
    old_expires = user["verification_expires_at"]
    try:
        r = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": user["email"]}, timeout=15)
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        assert GENERIC_MSG_FRAGMENT in r.json().get("message", "")
        after = db.users.find_one({"user_id": user["user_id"]})
        # Token regenerated
        assert after.get("verification_token") is not None
        assert after["verification_token"] != old_token
        # Expiration extended (different from old or same — must be in future ~24h)
        new_expiry = datetime.fromisoformat(after["verification_expires_at"].replace("Z", "+00:00"))
        delta = (new_expiry - now()).total_seconds()
        assert 23 * 3600 < delta < 25 * 3600, f"expiration not ~24h in future: {delta}s"
        # last_resend_at set to ~now
        assert after.get("last_resend_at") is not None
        last = datetime.fromisoformat(after["last_resend_at"].replace("Z", "+00:00"))
        assert abs((now() - last).total_seconds()) < 30
        # Still unverified
        assert after.get("email_verified") is False
    finally:
        _cleanup(db, user)


# ===== Rate-limit: two consecutive calls => second 429 =====
def test_resend_rate_limit_returns_429_on_second_call(db):
    user = _insert_user(db, verified=False)
    try:
        r1 = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": user["email"]}, timeout=15)
        assert r1.status_code == 200, f"first call: {r1.status_code}: {r1.text}"
        r2 = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": user["email"]}, timeout=15)
        assert r2.status_code == 429, f"second call should be 429, got {r2.status_code}: {r2.text}"
        detail = r2.json().get("detail", "")
        assert "espera" in detail.lower() or "s antes" in detail.lower(), f"unexpected detail: {detail}"
    finally:
        _cleanup(db, user)


# ===== Rate-limit bypassed when last_resend_at is older than cooldown =====
def test_resend_after_cooldown_succeeds(db):
    # Seed with last_resend_at 120s ago (> 60s cooldown)
    user = _insert_user(db, verified=False, last_resend=now() - timedelta(seconds=120))
    old_token = user["verification_token"]
    try:
        r = requests.post(f"{BASE_URL}/api/auth/resend-verification", json={"email": user["email"]}, timeout=15)
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        after = db.users.find_one({"user_id": user["user_id"]})
        assert after["verification_token"] != old_token
    finally:
        _cleanup(db, user)
