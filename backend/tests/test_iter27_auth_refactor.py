"""iter27 regression — verify auth endpoints behave identically after extraction
to routes/auth.py. Pure structural refactor, zero behavioral change expected."""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = BASE_URL + "/api"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
_mongo = MongoClient(MONGO_URL)[DB_NAME]


def _unique_email():
    return f"iter27_{uuid.uuid4().hex[:10]}@test.com"


def _cleanup(email):
    _mongo.users.delete_many({"email": email})
    _mongo.user_sessions.delete_many({})
    _mongo.login_attempts.delete_many({"identifier": email})


# ---- Smoke ----

def test_api_root_alive():
    r = requests.get(f"{API}/")
    assert r.status_code == 200


def test_openapi_path_count_unchanged():
    """Snapshot assertion — updated after each refactor that adds/removes paths.

    Hits the backend directly (localhost:8001) because the public ingress only
    forwards `/api/*`. iter33 split server.py into routes/* and exposed push +
    notifications endpoints; the count is now 80.
    """
    r = requests.get("http://localhost:8001/openapi.json")
    assert r.status_code == 200
    assert len(r.json()["paths"]) == 80


# ---- /auth/register ----

def test_register_valid_payload():
    email = _unique_email()
    _cleanup(email)
    r = requests.post(f"{API}/auth/register", json={
        "email": email,
        "password": "veryStrongPass123",
        "name": "Iter27 Reg",
        "phone": "+5350123999",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["email"] == email
    assert "message" in body
    u = _mongo.users.find_one({"email": email})
    assert u is not None
    assert u["email_verified"] is False
    assert u["password_hash"].startswith("$2b$")
    assert "verification_token" in u
    _cleanup(email)


def test_register_missing_phone_returns_422():
    r = requests.post(f"{API}/auth/register", json={
        "email": _unique_email(), "password": "veryStrongPass123", "name": "no phone",
    })
    assert r.status_code == 422


def test_register_invalid_phone_format_returns_422():
    email = _unique_email()
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": "veryStrongPass123",
        "name": "Bad Phone", "phone": "12345",  # missing + country code
    })
    assert r.status_code == 422


# ---- /auth/login ----

@pytest.fixture
def verified_user():
    email = _unique_email()
    _cleanup(email)
    requests.post(f"{API}/auth/register", json={
        "email": email, "password": "veryStrongPass123",
        "name": "Verified", "phone": "+5350123100",
    })
    # Manually mark verified in DB to skip mail step
    _mongo.users.update_one({"email": email}, {"$set": {"email_verified": True}, "$unset": {"verification_token": ""}})
    yield {"email": email, "password": "veryStrongPass123"}
    _cleanup(email)


def test_login_success_sets_cookie(verified_user):
    r = requests.post(f"{API}/auth/login", json=verified_user)
    assert r.status_code == 200, r.text
    assert "session_token" in r.cookies
    body = r.json()
    assert body["email"] == verified_user["email"]
    assert "password_hash" not in body
    # Cookie attrs (httponly/secure/samesite=none) -> in Set-Cookie raw
    raw = r.headers.get("set-cookie", "")
    assert "HttpOnly" in raw
    assert "Secure" in raw
    assert "samesite=none" in raw.lower() or "SameSite=None" in raw


def test_login_user_not_found_returns_404():
    r = requests.post(f"{API}/auth/login", json={"email": "nobody_xyz_iter27@x.com", "password": "any12345678"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "USER_NOT_FOUND"


def test_login_invalid_password_returns_401(verified_user):
    r = requests.post(f"{API}/auth/login", json={"email": verified_user["email"], "password": "WRONGwrong12345"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "INVALID_PASSWORD"


def test_login_email_not_verified_returns_403():
    email = _unique_email()
    _cleanup(email)
    requests.post(f"{API}/auth/register", json={
        "email": email, "password": "veryStrongPass123",
        "name": "Unverified", "phone": "+5350123200",
    })
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": "veryStrongPass123"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"
    _cleanup(email)


def test_login_brute_force_lockout(verified_user):
    # Trigger 5 wrong attempts → 6th should be 429
    for _ in range(5):
        requests.post(f"{API}/auth/login", json={"email": verified_user["email"], "password": "WRONGwrong00000"})
    r = requests.post(f"{API}/auth/login", json={"email": verified_user["email"], "password": "WRONGwrong00000"})
    assert r.status_code == 429
    # Cleanup attempts so other tests aren't blocked
    _mongo.login_attempts.delete_many({"identifier": verified_user["email"]})


# ---- /auth/verify-email/{token} ----

def test_verify_email_with_valid_token():
    email = _unique_email()
    _cleanup(email)
    requests.post(f"{API}/auth/register", json={
        "email": email, "password": "veryStrongPass123",
        "name": "VerifyMe", "phone": "+5350123300",
    })
    u = _mongo.users.find_one({"email": email})
    token = u["verification_token"]
    r = requests.get(f"{API}/auth/verify-email/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verified"] is True
    assert body["email"] == email
    # Cookie MUST NOT be set
    assert "session_token" not in r.cookies
    u2 = _mongo.users.find_one({"email": email})
    assert u2["email_verified"] is True
    assert "verification_token" not in u2
    _cleanup(email)


def test_verify_email_invalid_token_returns_400():
    r = requests.get(f"{API}/auth/verify-email/INVALIDTOKEN_NONEXISTENT")
    assert r.status_code == 400


# ---- /auth/resend-verification ----

def test_resend_verification_unverified_user():
    email = _unique_email()
    _cleanup(email)
    requests.post(f"{API}/auth/register", json={
        "email": email, "password": "veryStrongPass123",
        "name": "Resend", "phone": "+5350123400",
    })
    old = _mongo.users.find_one({"email": email})["verification_token"]
    # Wait so 60s cooldown logic re-issues (first resend has no last_resend_at)
    r = requests.post(f"{API}/auth/resend-verification", json={"email": email})
    assert r.status_code == 200
    new = _mongo.users.find_one({"email": email})["verification_token"]
    assert new != old
    # Immediate retry triggers cooldown
    r2 = requests.post(f"{API}/auth/resend-verification", json={"email": email})
    assert r2.status_code == 429
    _cleanup(email)


def test_resend_verification_nonexistent_returns_200_generic():
    r = requests.post(f"{API}/auth/resend-verification", json={"email": "nope_iter27_xyz@test.com"})
    assert r.status_code == 200


# ---- /auth/forgot-password & /auth/reset-password ----

def test_forgot_password_existing_user_sets_token(verified_user):
    r = requests.post(f"{API}/auth/forgot-password", json={"email": verified_user["email"]})
    assert r.status_code == 200
    u = _mongo.users.find_one({"email": verified_user["email"]})
    assert "password_reset_token" in u


def test_forgot_password_nonexistent_returns_200():
    r = requests.post(f"{API}/auth/forgot-password", json={"email": "noone_iter27_x@y.com"})
    assert r.status_code == 200


def test_reset_password_with_valid_token(verified_user):
    requests.post(f"{API}/auth/forgot-password", json={"email": verified_user["email"]})
    token = _mongo.users.find_one({"email": verified_user["email"]})["password_reset_token"]
    r = requests.post(f"{API}/auth/reset-password", json={"token": token, "password": "BrandNewPass77!"})
    assert r.status_code == 200
    # session cookie issued
    assert "session_token" in r.cookies
    # Old password should fail
    r_old = requests.post(f"{API}/auth/login", json={"email": verified_user["email"], "password": "veryStrongPass123"})
    assert r_old.status_code == 401
    # New password should work
    r_new = requests.post(f"{API}/auth/login", json={"email": verified_user["email"], "password": "BrandNewPass77!"})
    assert r_new.status_code == 200


# ---- /auth/me + /auth/logout ----

def test_auth_me_no_session_returns_401():
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401


def test_auth_me_with_session_returns_user(verified_user):
    s = requests.Session()
    s.post(f"{API}/auth/login", json=verified_user)
    r = s.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == verified_user["email"]


def test_logout_clears_session(verified_user):
    s = requests.Session()
    s.post(f"{API}/auth/login", json=verified_user)
    r = s.post(f"{API}/auth/logout")
    assert r.status_code == 200
    # After logout, /auth/me should be 401
    r2 = s.get(f"{API}/auth/me")
    assert r2.status_code == 401


# ---- /auth/google/login ----

def test_google_login_redirects_to_google():
    r = requests.get(f"{API}/auth/google/login", allow_redirects=False)
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers.get("location", "")
    # state token persisted
    state = r.headers["location"].split("state=")[1].split("&")[0]
    assert _mongo.oauth_states.find_one({"state": state}) is not None
