"""E34-03 — la verificación de retiro de una Empresa debe ser EMPRESARIAL (KYB).

Reglas verificadas:
- Una Empresa con email+teléfono verificados pero SIN verificación empresarial
  aprobada NO está verificada para retirar, aunque tenga un KYC personal
  aprobado (`kind` ausente). El guard es consciente del rol.
- Con una verificación `kind="company"` aprobada, la Empresa queda verificada.
- El CTA/enlace de verificación de una Empresa apunta a /company/kyc (no a
  /dashboard/kyc, que su router devolvería a /company → bucle).
- Revalidación: al reenviar una verificación empresarial ya aprobada, la
  aprobación anterior NO se conserva en silencio (pasa a 'superseded', la
  cuenta vuelve a 'pending' y los retiros se bloquean hasta re-aprobación).
- Clientes/VIP conservan su comportamiento (KYC personal aprobado los verifica).
"""
import asyncio
import os
import sys
import uuid

import requests
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import BASE_URL, ADMIN_TOKEN  # noqa: E402
from services.user_verification import (  # noqa: E402
    assert_user_fully_verified, get_user_verification_state)

API = f"{BASE_URL}/api"
EMP_ID = "user_test_e3403"
EMP_TOKEN = "test_session_e3403_X"
NORM_ID = "user_test_e3403_norm"

PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
       "QVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _amotor():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed():
    db = _db()
    from datetime import datetime, timezone, timedelta
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "e3403@example.com", "name": "Empresa E3403",
        "role": "empresa", "account_status": "active", "account_type": "business",
        "email_verified": True, "phone_verified": True, "phone": "+5350000333",
        "kyc_status": "unverified"}}, upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)
    db.kyc_verifications.delete_many({"user_id": EMP_ID})
    db.kyc_verifications.delete_many({"user_id": NORM_ID})


def _cleanup():
    db = _db()
    db.kyc_verifications.delete_many({"user_id": EMP_ID})
    db.kyc_verifications.delete_many({"user_id": NORM_ID})


def _insert_verif(user_id, status="verified", kind=None):
    db = _db()
    doc = {"id": str(uuid.uuid4()), "user_id": user_id, "status": status,
           "documents": [], "created_at": "2026-01-01T00:00:00+00:00",
           "updated_at": "2026-01-01T00:00:00+00:00"}
    if kind:
        doc["kind"] = kind
    db.kyc_verifications.insert_one(doc)
    return doc["id"]


class TestKYBWithdrawGuard:
    def setup_method(self, _):
        _seed()

    def teardown_method(self, _):
        _cleanup()

    def test_personal_kyc_does_not_verify_empresa(self):
        # Empresa con KYC PERSONAL aprobado (sin kind) → NO verificada.
        _insert_verif(EMP_ID, status="verified", kind=None)
        r = requests.get(f"{API}/auth/me", headers=_hdr(EMP_TOKEN))
        assert r.status_code == 200, r.text
        ver = r.json()["verification"]
        assert ver["kyc_verified"] is False
        assert "kyc" in ver["missing"]
        assert ver["fully_verified"] is False

    def test_company_kyc_verifies_empresa(self):
        _insert_verif(EMP_ID, status="verified", kind="company")
        r = requests.get(f"{API}/auth/me", headers=_hdr(EMP_TOKEN))
        assert r.status_code == 200, r.text
        ver = r.json()["verification"]
        assert ver["kyc_verified"] is True
        assert ver["fully_verified"] is True

    def test_guard_raises_business_cta_for_empresa(self):
        _insert_verif(EMP_ID, status="verified", kind=None)  # personal only
        user = {"user_id": EMP_ID, "role": "empresa",
                "email_verified": True, "phone_verified": True}
        db = _amotor()
        try:
            _run(assert_user_fully_verified(db, user, action_label="retirar fondos"))
            assert False, "debería bloquear por KYC empresarial"
        except HTTPException as exc:
            assert exc.status_code == 403
            assert exc.detail["code"] == "KYC_NOT_APPROVED"
            assert exc.detail["cta_url"] == "/company/kyc"

    def test_guard_passes_with_company_verification(self):
        _insert_verif(EMP_ID, status="verified", kind="company")
        user = {"user_id": EMP_ID, "role": "empresa",
                "email_verified": True, "phone_verified": True}
        db = _amotor()
        # No debe lanzar.
        _run(assert_user_fully_verified(db, user, action_label="retirar fondos"))

    def test_normal_user_cta_is_dashboard(self):
        user = {"user_id": NORM_ID, "role": "normal",
                "email_verified": True, "phone_verified": True}
        db = _amotor()
        try:
            _run(assert_user_fully_verified(db, user))
            assert False, "normal sin KYC debería bloquear"
        except HTTPException as exc:
            assert exc.detail["cta_url"] == "/dashboard/kyc"

    def test_normal_user_personal_kyc_verifies(self):
        _insert_verif(NORM_ID, status="verified", kind=None)
        user = {"user_id": NORM_ID, "role": "normal",
                "email_verified": True, "phone_verified": True}
        db = _amotor()
        state = _run(get_user_verification_state(db, user))
        assert state["kyc_verified"] is True
        assert state["fully_verified"] is True

    def test_revalidation_supersedes_approval(self):
        # Empresa verificada (kind=company) reenvía → la aprobación anterior
        # pasa a 'superseded', nueva pending, y deja de estar verificada.
        old_id = _insert_verif(EMP_ID, status="verified", kind="company")
        r = requests.post(f"{API}/kyc/company/submit", headers=_hdr(EMP_TOKEN), json={
            "fiscal_code": "RB-REVAL", "legal_address": "Dir nueva 456",
            "company_name": "Empresa E3403", "tax_certificate": PNG,
            "operating_license": PNG})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"
        db = _db()
        old = db.kyc_verifications.find_one({"id": old_id}, {"_id": 0, "status": 1})
        assert old["status"] == "superseded"
        rows = list(db.kyc_verifications.find(
            {"user_id": EMP_ID, "status": "pending"}, {"_id": 0}))
        assert len(rows) == 1
        # Ya no está verificada → retiros bloqueados hasta re-aprobación.
        me = requests.get(f"{API}/auth/me", headers=_hdr(EMP_TOKEN))
        assert me.json()["verification"]["kyc_verified"] is False
