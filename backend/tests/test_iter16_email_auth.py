"""Tests for iter16/iter17 — email/password auth + verification + reset (Cuba fallback)."""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL


TEST_EMAIL = os.environ.get("TEST_EMAIL_AUTH_EMAIL", "cuba.iter16@example.com")
TEST_PASSWORD = os.environ.get("TEST_EMAIL_AUTH_PWD", "veryStrongPass123")  # test-only fixture credential, not a real secret
TEST_NAME = "Iter16 Test User"
# iter23 made phone mandatory at register time. A single fixture phone is fine
# because each test cleans up the user (and therefore the phone) before running.
TEST_PHONE = "+5350000016"


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _cleanup():
    cli, db = _db()
    user = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0, "user_id": 1})
    if user:
        db.user_sessions.delete_many({"user_id": user["user_id"]})
    db.users.delete_many({"email": TEST_EMAIL})
    # iter23 — clean phone-based residue from previous test runs.
    db.users.delete_many({"phone": {"$in": [TEST_PHONE, "+5350000017"]}})
    db.login_attempts.delete_many({})  # clear rate limit history
    cli.close()


def _register():
    """Register and return (response, verification_token from DB)."""
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME, "phone": TEST_PHONE},
    )
    cli, db = _db()
    user = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0})
    cli.close()
    return r, user


def _verify(token):
    return requests.get(f"{BASE_URL}/api/auth/verify-email/{token}")


class TestEmailPasswordAuth:
    def setup_method(self, _): _cleanup()
    def teardown_method(self, _): _cleanup()

    # ---------- Registration ----------
    def test_register_creates_unverified_user(self):
        r, user = _register()
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["email"] == TEST_EMAIL
        # No session/role/hash leaked at register time
        assert "password_hash" not in body
        assert "session_token" not in r.cookies
        # DB shows unverified user with a verification token
        assert user["email_verified"] is False
        assert user["verification_token"]
        assert user["role"] == "normal" or user["role"] == "admin"

    def test_register_duplicate_email_rejected(self):
        _register()
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": "differentPass1234", "name": "Otro", "phone": "+5350000017"},
        )
        assert r.status_code == 409

    def test_register_invalid_email_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": "not-an-email", "password": TEST_PASSWORD, "name": TEST_NAME, "phone": TEST_PHONE},
        )
        assert r.status_code == 422

    def test_register_short_password_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": "short", "name": TEST_NAME, "phone": TEST_PHONE},
        )
        assert r.status_code == 422

    # ---------- Email Verification ----------
    def test_verify_email_logs_user_in(self):
        """iter28+ — verify-email confirms the address but does NOT auto-login.
        User has to sign in manually after clicking the link."""
        _r, user = _register()
        v = _verify(user["verification_token"])
        assert v.status_code == 200, v.text
        body = v.json()
        assert body["verified"] is True
        assert body["email"] == TEST_EMAIL
        # No password_hash / verification_token leaked in the response
        assert "password_hash" not in body
        assert "verification_token" not in body
        # iter28: verify-email is intentionally not a login — no session cookie.
        assert "session_token" not in v.cookies
        # DB state: email_verified=True, verification_token unset.
        cli, db = _db()
        fresh = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0})
        cli.close()
        assert fresh["email_verified"] is True
        assert "verification_token" not in fresh

    def test_verify_invalid_token_rejected(self):
        r = _verify("not-a-real-token-xxx")
        assert r.status_code == 400

    def test_verify_token_single_use(self):
        _r, user = _register()
        token = user["verification_token"]
        first = _verify(token)
        assert first.status_code == 200
        second = _verify(token)
        assert second.status_code == 400

    # ---------- Login ----------
    def test_login_blocked_until_verified(self):
        _register()
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert r.status_code == 403, r.text
        detail = r.json()["detail"]
        assert detail.get("code") == "EMAIL_NOT_VERIFIED"

    def test_login_works_after_verification(self):
        _r, user = _register()
        _verify(user["verification_token"])
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert r.status_code == 200, r.text
        assert "session_token" in r.cookies
        token = r.cookies["session_token"]
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == TEST_EMAIL

    def test_login_wrong_password_rejected(self):
        _r, user = _register()
        _verify(user["verification_token"])
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": "wrong-pass-1234"},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "INVALID_PASSWORD"

    def test_login_unknown_user_returns_user_not_found(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever-strong"},
        )
        assert r.status_code == 404
        body = r.json()["detail"]
        assert body["code"] == "USER_NOT_FOUND"
        assert "cuenta" in body["message"].lower()

    def test_login_google_only_account_returns_use_google(self):
        """User exists but has no password_hash (created via Google OAuth)."""
        cli, db = _db()
        db.users.insert_one({
            "user_id": "user_test_googleonly",
            "email": TEST_EMAIL,
            "name": "Google Only",
            "role": "normal",
            "auth_provider": "google",
            "email_verified": True,
        })
        cli.close()
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": "anyStrongPwd123"},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "USE_GOOGLE_LOGIN"

    def test_brute_force_locks_out_after_5_fails(self):
        _r, user = _register()
        _verify(user["verification_token"])
        for _ in range(5):
            requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": TEST_EMAIL, "password": "wrong"},
            )
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert r.status_code == 429

    def test_login_default_session_is_7_days(self):
        """Without remember_hours, session must default to 7d (168h)."""
        _r, user = _register()
        _verify(user["verification_token"])
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert r.status_code == 200
        token = r.cookies["session_token"]
        cli, db = _db()
        sess = db.user_sessions.find_one({"session_token": token})
        cli.close()
        # Expires roughly 7 days from now (allow 5 min skew)
        from datetime import datetime, timezone, timedelta
        exp = sess["expires_at"]
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, minutes=5)

    def test_login_with_remember_hours_24_creates_short_session(self):
        """remember_hours=24 must cap the session to 24h (login once a day)."""
        _r, user = _register()
        _verify(user["verification_token"])
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "remember_hours": 24},
        )
        assert r.status_code == 200
        token = r.cookies["session_token"]
        cli, db = _db()
        sess = db.user_sessions.find_one({"session_token": token})
        cli.close()
        from datetime import datetime, timezone, timedelta
        exp = sess["expires_at"]
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert timedelta(hours=23, minutes=55) <= delta <= timedelta(hours=24, minutes=5)

    def test_login_remember_hours_clamped_to_max_7d(self):
        """Out-of-range remember_hours must be clamped (no >7d sessions)."""
        _r, user = _register()
        _verify(user["verification_token"])
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "remember_hours": 99999},
        )
        assert r.status_code == 200
        token = r.cookies["session_token"]
        cli, db = _db()
        sess = db.user_sessions.find_one({"session_token": token})
        cli.close()
        from datetime import datetime, timezone, timedelta
        exp = sess["expires_at"]
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert delta <= timedelta(days=7, minutes=5)

    # ---------- Password Reset ----------
    def test_forgot_password_creates_token_for_known_user(self):
        _r, _user = _register()
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": TEST_EMAIL},
        )
        assert r.status_code == 200
        cli, db = _db()
        u = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0})
        cli.close()
        assert u.get("password_reset_token")

    def test_forgot_password_silent_for_unknown(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": "nobody-xyz@example.com"},
        )
        # Always 200 to avoid email enumeration
        assert r.status_code == 200

    def test_reset_password_updates_hash_and_verifies(self):
        _r, _user = _register()
        requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": TEST_EMAIL})
        cli, db = _db()
        token = db.users.find_one({"email": TEST_EMAIL})["password_reset_token"]
        cli.close()
        new_pwd = "BrandNewPwd9876"
        r = requests.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"token": token, "password": new_pwd},
        )
        assert r.status_code == 200, r.text
        # Old password rejected, new password works (and user is now verified)
        bad = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert bad.status_code == 401
        good = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": new_pwd},
        )
        assert good.status_code == 200, good.text

    def test_reset_password_invalid_token_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"token": "bogus-token-xxx", "password": "AnyValidPwd123"},
        )
        assert r.status_code == 400

    def test_reset_password_token_single_use(self):
        _r, _user = _register()
        requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": TEST_EMAIL})
        cli, db = _db()
        token = db.users.find_one({"email": TEST_EMAIL})["password_reset_token"]
        cli.close()
        first = requests.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"token": token, "password": "NewPwdOnce123"},
        )
        assert first.status_code == 200
        second = requests.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"token": token, "password": "NewPwdTwice456"},
        )
        assert second.status_code == 400
