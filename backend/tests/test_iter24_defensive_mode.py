"""iter24 — Defensive Mode: admin can freeze new registrations + withdrawals."""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL, make_admin_totp


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _reset_defensive():
    cli, db = _db()
    db.system_config.delete_many({"key": "defensive_mode"})
    db.users.delete_many({"email": {"$regex": "^iter24\\."}})
    cli.close()


def _toggle(enabled: bool, reason: str = "iter24 test"):
    return requests.post(
        f"{BASE_URL}/api/admin/defensive-mode/toggle",
        headers={"Authorization": "Bearer test_session_admin_X"},
        json={"enabled": enabled, "reason": reason, "totp_code": make_admin_totp()},
    )


class TestDefensiveMode:
    def setup_method(self, _): _reset_defensive()
    def teardown_method(self, _): _reset_defensive()

    # --- Toggle endpoint ---
    def test_admin_can_enable(self):
        r = _toggle(True, "iter24 attack")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is True
        assert body["reason"] == "iter24 attack"
        assert body["enabled_at"] is not None
        assert body["enabled_by_email"]

    def test_admin_can_disable(self):
        _toggle(True)
        r = _toggle(False)
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert r.json()["enabled_at"] is None

    def test_toggle_requires_admin_role(self):
        # Employee staff is NOT enough — admin only
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": "Bearer test_session_employee_X"},
            json={"enabled": True, "totp_code": make_admin_totp()},
        )
        assert r.status_code == 403

    def test_toggle_requires_totp(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={"enabled": True},  # no totp_code
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_CODE_REQUIRED"

    # --- Public GET ---
    def test_public_endpoint_open(self):
        _toggle(True, "open test")
        r = requests.get(f"{BASE_URL}/api/system/defensive-mode")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        # Reason NOT exposed publicly
        assert "reason" not in body
        assert "enabled_by_email" not in body

    def test_public_endpoint_defaults_to_off(self):
        r = requests.get(f"{BASE_URL}/api/system/defensive-mode")
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    # --- Enforcement on registration ---
    def test_registration_blocked_when_enabled(self):
        _toggle(True, "freeze")
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": "iter24.blocked@example.com", "password": "abcd1234",
                  "name": "Blocked", "phone": "+5350123456"},
        )
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "DEFENSIVE_MODE"
        assert "nuevos registros" in r.json()["detail"]["message"]

    def test_registration_works_when_disabled(self):
        # ensure off
        _toggle(True)
        _toggle(False)
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": "iter24.ok@example.com", "password": "abcd12345",
                  "name": "OK", "phone": "+5350987654"},
        )
        assert r.status_code == 200

    # --- Enforcement on withdrawals ---
    def test_normal_user_withdrawal_blocked_when_enabled(self):
        _toggle(True, "freeze withdrawals")
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw",
            headers={"Authorization": "Bearer test_session_normal_X"},
            json={"amount_usd": 10, "method": "transfer",
                  "beneficiary_name": "Test Beneficiary",
                  "details": "Bank xyz 0001-0002",
                  "totp_code": "000000"},
        )
        assert r.status_code == 503, r.text
        assert r.json()["detail"]["code"] == "DEFENSIVE_MODE"
        assert "retiros" in r.json()["detail"]["message"]

    def test_admin_withdrawal_bypasses_defensive_mode(self):
        """Admin must keep operating during defensive mode."""
        _toggle(True, "freeze")
        r = requests.post(
            f"{BASE_URL}/api/vip/withdraw",
            headers={"Authorization": "Bearer test_session_admin_X"},
            json={"amount_usd": 10, "method": "transfer",
                  "beneficiary_name": "Admin Test",
                  "details": "Bank xyz"},
        )
        if r.status_code == 503:
            assert r.json()["detail"].get("code") != "DEFENSIVE_MODE"

    # --- Audit log ---
    def test_toggle_creates_audit_entry(self):
        _toggle(True, "auditable reason")
        cli, db = _db()
        log = db.audit_log.find_one(
            {"action": "system.defensive_mode", "details.reason": "auditable reason"}
        )
        cli.close()
        assert log is not None
        assert log["details"]["reason"] == "auditable reason"
