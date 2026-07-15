"""iter23 — phone-based trust layer:
- phone required + E.164 validated on register
- blocked_contacts CRUD by admin/staff
- phone-or-email blocklist enforced at registration
- staff manually verifies phone (TOTP step-up)
- withdrawals blocked when phone exists but is not verified
- legacy users (no phone) unaffected
"""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL, make_admin_totp, NORMAL_TOKEN


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _cleanup_emails():
    cli, db = _db()
    db.users.delete_many({"email": {"$regex": "^iter23\\."}})
    db.user_sessions.delete_many({"user_id": {"$regex": "^user_test_phone_"}})
    db.blocked_contacts.delete_many({"reason": {"$regex": "^iter23_test"}})
    db.login_attempts.delete_many({})
    cli.close()


DEFAULT_TEST_PWD = os.environ.get("TEST_PHONE_TRUST_PWD", "strongPass123")  # test-only fixture


def _register(email, phone, password=DEFAULT_TEST_PWD, name="Test User"):
    return requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": name, "phone": phone},
    )


def _block(phone=None, email=None, reason="iter23_test block"):
    return requests.post(
        f"{BASE_URL}/api/admin/blocked-contacts",
        headers={"Authorization": "Bearer test_session_admin_X"},
        json={"phone": phone, "email": email, "reason": reason},
    )


class TestPhoneRegistration:
    def setup_method(self, _): _cleanup_emails()
    def teardown_method(self, _): _cleanup_emails()

    def test_register_requires_phone(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": "iter23.nophone@example.com", "password": "x" * 10, "name": "A"},
        )
        assert r.status_code == 422

    def test_register_validates_e164_format(self):
        r = _register("iter23.bad@example.com", "5350123456")  # no leading +
        assert r.status_code == 422
        assert "Formato" in r.json()["detail"]

    def test_register_accepts_valid_e164(self):
        r = _register("iter23.ok@example.com", "+5350123456")
        assert r.status_code == 200, r.text
        cli, db = _db()
        u = db.users.find_one({"email": "iter23.ok@example.com"})
        cli.close()
        assert u["phone"] == "+5350123456"
        assert u["phone_verified"] is False

    def test_register_strips_spaces_and_dashes(self):
        r = _register("iter23.fmt@example.com", "+53 50-12 34 56")
        assert r.status_code == 200
        cli, db = _db()
        u = db.users.find_one({"email": "iter23.fmt@example.com"})
        cli.close()
        assert u["phone"] == "+5350123456"

    def test_phone_uniqueness(self):
        _register("iter23.first@example.com", "+5350777888")
        r = _register("iter23.second@example.com", "+5350777888")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "PHONE_IN_USE"


class TestBlockedContacts:
    def setup_method(self, _): _cleanup_emails()
    def teardown_method(self, _): _cleanup_emails()

    def test_blocked_phone_rejects_registration(self):
        b = _block(phone="+5350BAD0001", reason="iter23_test scammer")
        assert b.status_code == 422  # not E.164 — good, our normalizer rejected the test data
        b = _block(phone="+5350001000", reason="iter23_test scammer")
        assert b.status_code == 200, b.text
        r = _register("iter23.scam@example.com", "+5350001000")
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "BLOCKED_CONTACT"

    def test_blocked_email_rejects_registration(self):
        b = _block(email="iter23.banned@example.com", reason="iter23_test ban")
        assert b.status_code == 200
        r = _register("iter23.banned@example.com", "+5350112233")
        assert r.status_code == 403

    def test_admin_can_list_and_delete_blocks(self):
        b = _block(phone="+5350998877", reason="iter23_test del")
        assert b.status_code == 200
        cid = b.json()["id"]
        lst = requests.get(
            f"{BASE_URL}/api/admin/blocked-contacts",
            headers={"Authorization": "Bearer test_session_admin_X"},
        )
        assert lst.status_code == 200
        assert any(item["id"] == cid for item in lst.json()["items"])
        d = requests.delete(
            f"{BASE_URL}/api/admin/blocked-contacts/{cid}",
            headers={"Authorization": "Bearer test_session_admin_X"},
        )
        assert d.status_code == 200

    def test_non_staff_cannot_block(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/blocked-contacts",
            headers={"Authorization": "Bearer test_session_normal_X"},
            json={"phone": "+5300000001", "reason": "iter23_test"},
        )
        assert r.status_code == 403

    def test_duplicate_block_rejected(self):
        _block(phone="+5350111222", reason="iter23_test")
        r = _block(phone="+5350111222", reason="iter23_test dup")
        assert r.status_code == 409


class TestPhoneVerification:
    def setup_method(self, _): _cleanup_emails()
    def teardown_method(self, _): _cleanup_emails()

    def test_staff_can_verify_phone(self):
        _register("iter23.verify@example.com", "+5350666777")
        cli, db = _db()
        u = db.users.find_one({"email": "iter23.verify@example.com"})
        cli.close()
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{u['user_id']}/verify-phone",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={"totp_code": make_admin_totp()},
        )
        assert r.status_code == 200, r.text
        assert r.json()["user"]["phone_verified"] is True

    def test_verify_phone_requires_totp(self):
        _register("iter23.totp@example.com", "+5350444555")
        cli, db = _db()
        u = db.users.find_one({"email": "iter23.totp@example.com"})
        cli.close()
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{u['user_id']}/verify-phone",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_CODE_REQUIRED"

    def test_verify_phone_fails_without_phone_set(self):
        # Defensive: some sibling tests seed a phone on this user. Unset it so
        # the "phone not set" path is actually exercised.
        cli, db = _db()
        db.users.update_one(
            {"user_id": "user_test_normal01"},
            {"$unset": {"phone": "", "phone_verified": ""}},
        )
        cli.close()
        r = requests.post(
            f"{BASE_URL}/api/admin/users/user_test_normal01/verify-phone",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={"totp_code": make_admin_totp()},
        )
        assert r.status_code == 400


class TestSelfServicePhone:
    """Google OAuth user updates their own phone via /api/me/phone."""

    def teardown_method(self, _): _cleanup_emails()

    def test_user_can_set_own_phone(self):
        # Use legacy normal test user (no phone)
        r = requests.post(
            f"{BASE_URL}/api/me/phone",
            headers={"Authorization": "Bearer test_session_normal_X"},
            json={"phone": "+5350999000"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["phone"] == "+5350999000"
        assert r.json()["phone_verified"] is False
        # Cleanup: restore legacy state (no phone)
        cli, db = _db()
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$unset": {"phone": "", "phone_verified": ""}})
        cli.close()


def test_legacy_users_can_still_withdraw_without_phone():
    """iter55.36o — legacy "phone=None bypass" was removed. This test now
    verifies the OPPOSITE: users without a phone are still blocked from
    withdrawing (the strict verification gate requires phone verified).

    Kept as a regression marker so we don't accidentally re-introduce the
    legacy bypass — it was intentionally deprecated when we tightened the
    exchange/withdraw gate to require email + phone + KYC.
    """
    cli, db = _db()
    # Force legacy state (no phone) then re-seed sessions
    db.users.update_one(
        {"user_id": "user_test_normal01"},
        {"$unset": {"phone": "", "phone_verified": ""}},
    )
    cli.close()

    # Attempt a withdrawal — should be blocked by the new gate.
    r = requests.post(
        f"{BASE_URL}/api/vip/withdraw",
        headers={"Authorization": f"Bearer {NORMAL_TOKEN}"},
        json={"amount_usd": 5, "method": "transfer",
              "beneficiary_name": "Legacy Test",
              "details": "Bank / dummy details for cash flow",
              "totp_code": "000000"},
    )
    assert r.status_code == 403, r.text
    detail = r.json().get("detail", {})
    # Any of the 3 verification codes is a valid failure here; the point is
    # that the user is NO longer waved through simply because `phone` is None.
    assert detail.get("code") in (
        "PHONE_NOT_VERIFIED", "EMAIL_NOT_VERIFIED", "KYC_NOT_APPROVED",
    )
