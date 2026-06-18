"""Tests for iter16 — email/password auth (Cuba/geo-restricted users fallback)."""
import os
import requests
import pytest
from pymongo import MongoClient

from conftest import BASE_URL


TEST_EMAIL = "cuba.iter16@example.com"
TEST_PASSWORD = "veryStrongPass123"
TEST_NAME = "Iter16 Test User"


def _cleanup():
    cli = MongoClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    user = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0, "user_id": 1})
    if user:
        db.user_sessions.delete_many({"user_id": user["user_id"]})
    db.users.delete_many({"email": TEST_EMAIL})
    db.login_attempts.delete_many({})  # clear rate limit history
    cli.close()


class TestEmailPasswordAuth:
    def setup_method(self, _): _cleanup()
    def teardown_method(self, _): _cleanup()

    def test_register_creates_user_and_session(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == TEST_EMAIL
        assert body["role"] == "normal"
        # Hash must NOT be returned
        assert "password_hash" not in body
        assert "session_token" in r.cookies

    def test_register_duplicate_email_rejected(self):
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME},
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": "differentPass1234", "name": "Otro"},
        )
        assert r.status_code == 409

    def test_register_invalid_email_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": "not-an-email", "password": TEST_PASSWORD, "name": TEST_NAME},
        )
        assert r.status_code == 422

    def test_register_short_password_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": "short", "name": TEST_NAME},
        )
        assert r.status_code == 422

    def test_login_returns_session(self):
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME},
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert r.status_code == 200, r.text
        assert "session_token" in r.cookies
        # /me works with the cookie
        token = r.cookies["session_token"]
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == TEST_EMAIL

    def test_login_wrong_password_rejected(self):
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME},
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": "wrong-pass-1234"},
        )
        assert r.status_code == 401

    def test_login_unknown_user_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever-strong"},
        )
        assert r.status_code == 401

    def test_brute_force_locks_out_after_5_fails(self):
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "name": TEST_NAME},
        )
        # 5 failed attempts
        for _ in range(5):
            requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": TEST_EMAIL, "password": "wrong"},
            )
        # 6th — should be rate-limited
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert r.status_code == 429
