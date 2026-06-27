"""Tests for iter18 — first-visit onboarding tour flag."""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL


TEST_EMAIL = os.environ.get("TEST_ONBOARDING_EMAIL", "onboarding.iter18@example.com")
TEST_PASSWORD = os.environ.get("TEST_ONBOARDING_PWD", "veryStrongPass123")  # test-only fixture
TEST_NAME = "Onboarding Test"


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _cleanup():
    cli, db = _db()
    user = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0, "user_id": 1})
    if user:
        db.user_sessions.delete_many({"user_id": user["user_id"]})
    db.users.delete_many({"email": TEST_EMAIL})
    db.login_attempts.delete_many({})
    cli.close()


def _register_and_login():
    """Register + verify (iter25 — verify no longer auto-logs in) + login.
    Returns (user_doc, session_token)."""
    requests.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": TEST_NAME,
            "phone": "+5350000018",
        },
    )
    cli, db = _db()
    user = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0})
    cli.close()
    requests.get(f"{BASE_URL}/api/auth/verify-email/{user['verification_token']}")
    # iter25 — verify-email no longer creates a session; user must log in.
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    return user, r.cookies["session_token"]


class TestOnboardingFlag:
    def setup_method(self, _): _cleanup()
    def teardown_method(self, _): _cleanup()

    def test_new_email_user_has_onboarding_false(self):
        user, _token = _register_and_login()
        assert user["onboarding_completed"] is False

    def test_me_endpoint_exposes_onboarding_flag(self):
        _user, token = _register_and_login()
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert me["onboarding_completed"] is False

    def test_complete_onboarding_endpoint_sets_flag_true(self):
        _user, token = _register_and_login()
        r = requests.post(
            f"{BASE_URL}/api/me/onboarding/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert me["onboarding_completed"] is True

    def test_complete_onboarding_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/me/onboarding/complete")
        assert r.status_code == 401

    def test_complete_onboarding_is_idempotent(self):
        _user, token = _register_and_login()
        r1 = requests.post(
            f"{BASE_URL}/api/me/onboarding/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        r2 = requests.post(
            f"{BASE_URL}/api/me/onboarding/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200 and r2.status_code == 200
