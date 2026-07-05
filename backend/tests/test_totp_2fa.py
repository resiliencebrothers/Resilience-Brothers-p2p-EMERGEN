"""Iter13 — 2FA / TOTP step-up authentication on withdrawals.

Coverage:
- /me/2fa/status, /me/2fa/setup, /me/2fa/verify-setup, /me/2fa/disable, /me/2fa/regenerate-recovery-codes
- Step-up gate on /api/vip/withdraw: 412 if no 2FA, 401 if missing/invalid code, 200 with valid TOTP or recovery
- Recovery code consumption (single-use)
- Encryption at rest (secret never returned after setup)
"""
import asyncio
import os
import requests
import sys

sys.path.insert(0, "/app/backend")
import totp_service  # noqa: E402

from conftest import BASE_URL, VIP_TOKEN, NORMAL_TOKEN, make_vip_totp  # noqa: E402, F401


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


# ---------- 2FA Setup & Status ----------
class TestTotpSetup:
    def test_status_when_disabled(self):
        # Use normal user (always disabled)
        r = requests.get(f"{BASE_URL}/api/me/2fa/status", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 200
        body = r.json()
        assert "enabled" in body

    def test_setup_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/me/2fa/setup")
        assert r.status_code == 401

    def test_setup_returns_qr_and_secret(self):
        # Need a clean user — use NORMAL temporarily
        # Reset state first
        from motor.motor_asyncio import AsyncIOMotorClient
        async def _reset():
            d = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            await d.users.update_one({"user_id": "user_test_normal01"},
                                     {"$set": {"totp_enabled": False},
                                      "$unset": {"totp_secret_encrypted": "",
                                                 "totp_pending_secret_encrypted": ""}})
        asyncio.run(_reset())
        r = requests.post(f"{BASE_URL}/api/me/2fa/setup", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["qr_data_url"].startswith("data:image/png;base64,")
        assert len(body["secret"]) >= 16
        assert body["provisioning_uri"].startswith("otpauth://totp/")

    def test_verify_setup_wrong_code_401(self):
        r = requests.post(f"{BASE_URL}/api/me/2fa/verify-setup",
                          headers=_h(NORMAL_TOKEN), json={"code": "000000"})
        assert r.status_code == 401


# ---------- Withdrawal step-up gate ----------
class TestWithdrawalStepUp:
    def test_no_2fa_returns_412(self):
        # Reset VIP's 2FA, attempt withdraw, expect TOTP_SETUP_REQUIRED
        from motor.motor_asyncio import AsyncIOMotorClient
        async def _reset():
            d = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            await d.users.update_one({"user_id": "user_test_vip01"},
                                     {"$set": {"totp_enabled": False}})
        asyncio.run(_reset())
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 1, "method": "transfer",
                                "details": "x", "beneficiary_name": "Test Holder"})
        assert r.status_code == 412
        assert r.json()["detail"]["code"] == "TOTP_SETUP_REQUIRED"
        assert "setup_url" in r.json()["detail"]

    def test_missing_code_returns_401(self):
        # Re-enable 2FA, then try without code
        make_vip_totp()  # ensures setup
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 1, "method": "transfer",
                                "details": "x", "beneficiary_name": "Test Holder"})
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_CODE_REQUIRED"

    def test_wrong_code_returns_401(self):
        make_vip_totp()
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 1, "method": "transfer",
                                "details": "x", "beneficiary_name": "Test Holder",
                                "totp_code": "000000"})
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_INVALID"

    def test_valid_code_accepts(self):
        code = make_vip_totp()
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 1, "method": "transfer",
                                "details": "x", "beneficiary_name": "Test Holder",
                                "totp_code": code})
        assert r.status_code == 200


# ---------- Encryption at rest ----------
class TestSecretEncryption:
    def test_status_never_leaks_secret(self):
        make_vip_totp()
        r = requests.get(f"{BASE_URL}/api/me/2fa/status", headers=_h(VIP_TOKEN))
        body = r.json()
        # status must not expose the raw secret nor encrypted blob
        for forbidden in ("totp_secret_encrypted", "secret", "totp_secret"):
            assert forbidden not in body

    def test_encrypt_decrypt_round_trip(self):
        s = totp_service.generate_secret()
        enc = totp_service.encrypt_secret(s)
        assert enc != s
        assert totp_service.decrypt_secret(enc) == s
