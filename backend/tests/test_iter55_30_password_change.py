"""iter55.30 — Self-service password change endpoint.

User complaint (12 Feb 2026): "en la sección de seguridad debería existir la
opción para el cliente de cambiar la contraseña" — previously the client only
had 2FA management under /dashboard/security, and password reset required a
"forgot password" flow via email token.

New endpoint: `POST /api/profile/password/change` with body
`{current_password, new_password, totp_code?}`. Rules:
  - Only for `auth_provider == "password"` accounts (Google users → 403).
  - Verify current password.
  - New must differ from current.
  - Require TOTP step-up if user has 2FA enabled.
  - Revoke all OTHER sessions (keep current one alive).
  - Send security email + write audit_log entry.
"""
import os
import uuid
import bcrypt
import pyotp
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, VIP_TOKEN, ADMIN_TOKEN

API = f"{API_ROOT}/api"

# Deterministic TOTP secret (same one used by the conftest for other test users)
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _fresh_totp() -> str:
    return pyotp.TOTP(TOTP_SECRET).now()


TEST_EMAIL = "pwd.change.test@resilience.com"
TEST_UID = "user_test_pwdchg01"
TEST_SESSION = "test_session_pwdchg_X"
INITIAL_PW = "OldPassword123!"


def _setup_password_user(twofa_enabled: bool = True):
    """Provision a fresh email/password test user with a known password
    hash + an active session token so we can hit /profile/password/change.

    Since the platform requires 2FA setup for sensitive operations (email
    change, phone change, password change), we default to twofa_enabled=True
    and seed the same deterministic TOTP secret used by conftest.
    """
    db_ = _db()
    doc = {
        "user_id": TEST_UID,
        "email": TEST_EMAIL,
        "name": "PwdChange Test",
        "role": "normal",
        "auth_provider": "password",
        "password_hash": _hash(INITIAL_PW),
        "email_verified": True,
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if twofa_enabled:
        import totp_service as _ts
        doc["totp_enabled"] = True
        doc["totp_secret_encrypted"] = _ts.encrypt_secret(TOTP_SECRET)
        doc["totp_recovery_codes"] = []
        doc["totp_setup_at"] = "2026-01-01T00:00:00+00:00"
    else:
        doc["totp_enabled"] = False
    db_.users.update_one({"user_id": TEST_UID}, {"$set": doc}, upsert=True)
    # Active session so require_user() succeeds
    now = datetime.now(timezone.utc)
    expires = now.replace(year=now.year + 1)  # 1-year for test convenience
    db_.user_sessions.update_one(
        {"session_token": TEST_SESSION},
        {"$set": {
            "session_token": TEST_SESSION,
            "user_id": TEST_UID,
            "expires_at": expires,
            "created_at": now,
        }},
        upsert=True,
    )


def _cleanup():
    db_ = _db()
    db_.users.delete_many({"user_id": TEST_UID})
    db_.user_sessions.delete_many({"user_id": TEST_UID})
    db_.audit_log.delete_many({"actor_id": TEST_UID})


def _pwd_hdr():
    return {"Authorization": f"Bearer {TEST_SESSION}", "Content-Type": "application/json"}


# ============================================================
# Endpoint tests
# ============================================================

def test_change_password_happy_path():
    """Fresh 2FA-enabled user: current_password + new_password + totp → 200
    + hash updated in Mongo + password_changed_at timestamped."""
    _setup_password_user()
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": "NewPassw0rd!",
                  "totp_code": _fresh_totp()},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "other_sessions_revoked" in body

        # Verify hash actually updated
        fresh = _db().users.find_one({"user_id": TEST_UID})
        assert bcrypt.checkpw(b"NewPassw0rd!", fresh["password_hash"].encode())
        assert not bcrypt.checkpw(INITIAL_PW.encode(), fresh["password_hash"].encode())
        assert "password_changed_at" in fresh
    finally:
        _cleanup()


def test_change_password_wrong_current_rejected():
    """Wrong current password → 400 with Spanish message; hash unchanged."""
    _setup_password_user()
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": "WrongOldPassword!", "new_password": "NewPassw0rd!",
                  "totp_code": _fresh_totp()},
        )
        assert r.status_code == 400, r.text
        assert "contraseña actual" in r.json()["detail"].lower()

        # Hash unchanged
        fresh = _db().users.find_one({"user_id": TEST_UID})
        assert bcrypt.checkpw(INITIAL_PW.encode(), fresh["password_hash"].encode())
    finally:
        _cleanup()


def test_change_password_same_as_current_rejected():
    """New must differ from current."""
    _setup_password_user()
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": INITIAL_PW,
                  "totp_code": _fresh_totp()},
        )
        assert r.status_code == 400, r.text
        assert "diferente" in r.json()["detail"].lower()
    finally:
        _cleanup()


def test_change_password_too_short_rejected_by_pydantic():
    """new_password must be at least 8 chars — Pydantic rejects earlier
    stages so we get a 422."""
    _setup_password_user()
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": "short",
                  "totp_code": _fresh_totp()},
        )
        assert r.status_code == 422, r.text
    finally:
        _cleanup()


def test_change_password_requires_2fa_setup_first():
    """User without 2FA enabled → 412 TOTP_SETUP_REQUIRED (consistent with
    email/phone change flows in profile.py). Guides the client to
    /dashboard/security first."""
    _setup_password_user(twofa_enabled=False)
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": "NewPassw0rd!"},
        )
        assert r.status_code == 412, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "TOTP_SETUP_REQUIRED"
    finally:
        _cleanup()


def test_change_password_wrong_totp_rejected():
    """Wrong TOTP code → 401 TOTP_INVALID. Hash unchanged."""
    _setup_password_user()
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": "NewPassw0rd!",
                  "totp_code": "000000"},
        )
        assert r.status_code == 401, r.text
        fresh = _db().users.find_one({"user_id": TEST_UID})
        assert bcrypt.checkpw(INITIAL_PW.encode(), fresh["password_hash"].encode())
    finally:
        _cleanup()


def test_change_password_google_user_forbidden():
    """Google-auth account has no password_hash → 403 with Spanish message."""
    db_ = _db()
    db_.users.update_one(
        {"user_id": TEST_UID},
        {"$set": {
            "user_id": TEST_UID,
            "email": TEST_EMAIL,
            "auth_provider": "google",
            "role": "normal",
            "account_status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, "$unset": {"password_hash": ""}},
        upsert=True,
    )
    now = datetime.now(timezone.utc)
    db_.user_sessions.update_one(
        {"session_token": TEST_SESSION},
        {"$set": {"session_token": TEST_SESSION, "user_id": TEST_UID,
                  "expires_at": now.replace(year=now.year + 1),
                  "created_at": now}},
        upsert=True,
    )
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": "whatever", "new_password": "AnyValidPass1!"},
        )
        assert r.status_code == 403, r.text
        assert "google" in r.json()["detail"].lower()
    finally:
        _cleanup()


def test_change_password_revokes_other_sessions():
    """After a successful change, other sessions of this user MUST be
    deleted; the current session stays alive."""
    _setup_password_user()
    db_ = _db()
    # Plant 2 extra sessions
    now = datetime.now(timezone.utc)
    exp = now.replace(year=now.year + 1)
    for extra in ("test_session_pwdchg_other1", "test_session_pwdchg_other2"):
        db_.user_sessions.update_one(
            {"session_token": extra},
            {"$set": {"session_token": extra, "user_id": TEST_UID,
                      "expires_at": exp, "created_at": now}},
            upsert=True,
        )
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": "NewPassw0rd!",
                  "totp_code": _fresh_totp()},
        )
        assert r.status_code == 200, r.text
        assert r.json()["other_sessions_revoked"] == 2

        # Other sessions gone, current one still alive
        remaining = list(db_.user_sessions.find({"user_id": TEST_UID}))
        assert len(remaining) == 1
        assert remaining[0]["session_token"] == TEST_SESSION
    finally:
        _cleanup()
        _db().user_sessions.delete_many({"session_token": {
            "$in": ["test_session_pwdchg_other1", "test_session_pwdchg_other2"]}})


def test_profile_me_exposes_auth_provider():
    """GET /profile/me must include `auth_provider` so the frontend gates
    the password change section vs the Google users message."""
    _setup_password_user()
    try:
        r = requests.get(f"{API}/profile/me", headers=_pwd_hdr())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["auth_provider"] == "password"
    finally:
        _cleanup()


def test_audit_log_records_password_change():
    """Every password change must land in audit_log for compliance."""
    _setup_password_user()
    try:
        r = requests.post(
            f"{API}/profile/password/change", headers=_pwd_hdr(),
            json={"current_password": INITIAL_PW, "new_password": "NewPassw0rd!",
                  "totp_code": _fresh_totp()},
        )
        assert r.status_code == 200, r.text
        entry = _db().audit_log.find_one(
            {"actor_id": TEST_UID, "action": "profile.password_changed"},
            sort=[("created_at", -1)],
        )
        assert entry is not None
        assert "contraseña" in entry.get("summary", "").lower()
    finally:
        _cleanup()
