"""iter246 — Cloudflare Turnstile ("No soy un robot") en registro/login email.

El entorno corre con claves REALES y TURNSTILE_ENFORCED=true. La suite de
tests inyecta el header X-Captcha-Bypass (conftest) con el secreto de .env;
un header explícito incorrecto permite probar el rechazo real.
"""
import os
import random
import uuid

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
MARK = "iter246captcha"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


class TestCaptchaConfig:
    def test_public_config_exposes_site_key_not_secrets(self):
        r = requests.get(f"{API}/captcha/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["site_key"].startswith("0x")
        assert body["enforced"] is True
        raw = r.text.lower()
        assert os.environ["TURNSTILE_SECRET_KEY"].lower() not in raw
        assert os.environ["TURNSTILE_TEST_BYPASS"].lower() not in raw


class TestCaptchaOnAuth:
    def teardown_method(self, _):
        _db().users.delete_many({"email": {"$regex": f"^{MARK}"}})

    def _register(self, token=None, headers=None):
        suffix = uuid.uuid4().hex[:8]
        digits = "".join(random.choices("0123456789", k=7))
        body = {"email": f"{MARK}.{suffix}@example.com", "password": "Password123!",
                "name": "Captcha Test", "phone": f"+535{digits}"}
        if token is not None:
            body["captcha_token"] = token
        return requests.post(f"{API}/auth/register", json=body, headers=headers)

    def test_register_with_suite_bypass_passes(self):
        r = self._register()
        assert r.status_code == 200, r.text

    def test_register_without_token_blocked_when_enforced(self):
        r = self._register(headers={"X-Captcha-Bypass": "wrong-bypass"})
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "CAPTCHA_REQUIRED"

    def test_register_with_forged_token_rejected_by_cloudflare(self):
        r = self._register(token="XXXX.FORGED.TOKEN",
                           headers={"X-Captcha-Bypass": "wrong-bypass"})
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "CAPTCHA_FAILED"

    def test_login_without_token_blocked_when_enforced(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": f"{MARK}.x@example.com",
                                "password": "Whatever123!"},
                          headers={"X-Captcha-Bypass": "wrong-bypass"})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "CAPTCHA_REQUIRED"


class TestVerifyHelper:
    @pytest.mark.asyncio
    async def test_enforced_requires_token(self, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        from captcha import verify_captcha_token
        from fastapi import HTTPException

        monkeypatch.setenv("TURNSTILE_ENFORCED", "true")

        class FakeReq:
            headers = {}

        with pytest.raises(HTTPException) as exc:
            await verify_captcha_token("", FakeReq())
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "CAPTCHA_REQUIRED"

    @pytest.mark.asyncio
    async def test_always_fail_secret_rejects_token(self, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        from captcha import verify_captcha_token
        from fastapi import HTTPException

        # clave de prueba oficial de Cloudflare que SIEMPRE rechaza
        monkeypatch.setenv("TURNSTILE_SECRET_KEY",
                           "2x0000000000000000000000000000000AA")

        class FakeReq:
            headers = {}

        with pytest.raises(HTTPException) as exc:
            await verify_captcha_token("some-token", FakeReq())
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "CAPTCHA_FAILED"
