"""iter20: admin can manually verify a user's email when Resend isn't sending."""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL, make_admin_totp


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


TEST_EMAIL = "manual.verify.iter20@example.com"
TEST_PWD = "veryStrongPass123"


def _cleanup():
    cli, db = _db()
    db.users.delete_many({"email": TEST_EMAIL})
    db.login_attempts.delete_many({})
    cli.close()


def _register():
    requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PWD, "name": "Manual"},
    )
    cli, db = _db()
    u = db.users.find_one({"email": TEST_EMAIL}, {"_id": 0})
    cli.close()
    return u


def _admin_verify(user_id: str):
    return requests.post(
        f"{BASE_URL}/api/admin/users/{user_id}/verify-email",
        headers={"Authorization": "Bearer test_session_admin_X"},
        json={"totp_code": make_admin_totp()},
    )


class TestAdminManualVerify:
    def setup_method(self, _): _cleanup()
    def teardown_method(self, _): _cleanup()

    def test_admin_can_verify_user_email(self):
        target = _register()
        assert target["email_verified"] is False
        r = _admin_verify(target["user_id"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["already_verified"] is False
        assert body["user"]["email_verified"] is True
        login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PWD},
        )
        assert login.status_code == 200, login.text

    def test_verify_again_is_idempotent(self):
        target = _register()
        first = _admin_verify(target["user_id"])
        assert first.status_code == 200
        second = _admin_verify(target["user_id"])
        assert second.status_code == 200
        assert second.json()["already_verified"] is True

    def test_unknown_user_returns_404(self):
        r = _admin_verify("user_does_not_exist")
        assert r.status_code == 404

    def test_non_staff_cannot_verify(self):
        target = _register()
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{target['user_id']}/verify-email",
            headers={"Authorization": "Bearer test_session_normal_X"},
            json={},
        )
        assert r.status_code == 403

    def test_anonymous_cannot_verify(self):
        target = _register()
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{target['user_id']}/verify-email",
            json={},
        )
        assert r.status_code == 401

    def test_requires_totp_step_up(self):
        target = _register()
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{target['user_id']}/verify-email",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={},  # no totp_code
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_CODE_REQUIRED"

    def test_verification_token_cleared_after_manual_verify(self):
        target = _register()
        assert target.get("verification_token")
        _admin_verify(target["user_id"])
        cli, db = _db()
        fresh = db.users.find_one({"user_id": target["user_id"]})
        cli.close()
        assert fresh["email_verified"] is True
        assert "verification_token" not in fresh

    def test_audit_log_entry_created(self):
        target = _register()
        _admin_verify(target["user_id"])
        cli, db = _db()
        log = db.audit_log.find_one({"action": "user.verify_email_manual", "entity_id": target["user_id"]})
        cli.close()
        assert log is not None
        assert TEST_EMAIL in log.get("summary", "")
