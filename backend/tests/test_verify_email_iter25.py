"""Backend tests for /api/auth/verify-email/{token} (iter25 bugfix).
Validates: no session cookie set on success, returns {verified, email, name},
DB cleanup of verification fields, idempotent behavior, invalid + expired token errors.
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/') if os.environ.get('REACT_APP_BACKEND_URL') else None
if not BASE_URL:
    # fallback to frontend .env
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                BASE_URL = line.split('=',1)[1].strip().strip('"').rstrip('/')
                break

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"

def iso(dt): return dt.isoformat()
def now(): return datetime.now(timezone.utc)


@pytest.fixture
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _insert_user(db, *, verified=False, expired=False, token=None):
    tok = token or (uuid.uuid4().hex + uuid.uuid4().hex)
    expires = now() - timedelta(hours=1) if expired else now() + timedelta(hours=24)
    email = f"TEST_verify_{uuid.uuid4().hex[:8]}@example.com"
    doc = {
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "email": email,
        "name": "Verify Test User",
        "role": "normal",
        "auth_provider": "password",
        "password_hash": "fake_hash",
        "email_verified": verified,
        "verification_token": tok,
        "verification_expires_at": iso(expires),
        "created_at": iso(now()),
    }
    db.users.insert_one(doc)
    return doc


def _cleanup(db, user):
    db.users.delete_one({"user_id": user["user_id"]})


# ===== Valid token =====
def test_verify_email_valid_returns_data_and_no_session(db):
    user = _insert_user(db)
    try:
        r = requests.get(f"{BASE_URL}/api/auth/verify-email/{user['verification_token']}", timeout=15, allow_redirects=False)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("verified") is True
        assert data.get("email") == user["email"]
        assert data.get("name") == user["name"]
        # CRITICAL: no Set-Cookie for session_token (must NOT auto-login)
        set_cookie = r.headers.get("set-cookie", "") or ""
        assert "session_token" not in set_cookie.lower(), f"Unexpected session cookie set: {set_cookie}"
        # DB state: email_verified=True, verification_token + verification_expires_at removed
        fresh = db.users.find_one({"user_id": user["user_id"]})
        assert fresh["email_verified"] is True
        assert "verification_token" not in fresh
        assert "verification_expires_at" not in fresh
    finally:
        _cleanup(db, user)


# ===== Invalid token =====
def test_verify_email_invalid_returns_400():
    r = requests.get(f"{BASE_URL}/api/auth/verify-email/nonexistent_token_xyz_12345", timeout=15)
    assert r.status_code == 400
    data = r.json()
    detail = data.get("detail", "")
    assert "Token inválido" in detail or "inválido" in detail.lower(), f"Unexpected detail: {detail}"


# ===== Expired token =====
def test_verify_email_expired_returns_400(db):
    user = _insert_user(db, expired=True)
    try:
        r = requests.get(f"{BASE_URL}/api/auth/verify-email/{user['verification_token']}", timeout=15)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "expiró" in detail.lower() or "expir" in detail.lower(), f"Unexpected detail: {detail}"
    finally:
        _cleanup(db, user)


# ===== Reusing same token after success =====
def test_verify_email_reuse_returns_400(db):
    user = _insert_user(db)
    token = user["verification_token"]
    try:
        r1 = requests.get(f"{BASE_URL}/api/auth/verify-email/{token}", timeout=15)
        assert r1.status_code == 200
        # Second use: token has been $unset, so should be 400
        r2 = requests.get(f"{BASE_URL}/api/auth/verify-email/{token}", timeout=15)
        assert r2.status_code == 400
        assert "inválido" in r2.json().get("detail", "").lower()
    finally:
        _cleanup(db, user)
