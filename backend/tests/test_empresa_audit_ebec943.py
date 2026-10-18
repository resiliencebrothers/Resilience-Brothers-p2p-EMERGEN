"""Auditoría del rol Empresa (commit ebec943) — regresiones de las correcciones.

EMP-A02 — las rutas de verificar/rechazar teléfono NO deben devolver campos de
          credenciales (password_hash, verification_token, secretos 2FA) en el
          documento `user`. Cubre las tres ramas: verificar, ya-verificado y
          rechazar.
EMP-A03 — el bloqueo masivo por teléfono debe suspender también a las cuentas
          `empresa` (pasar a under_review + perder phone_verified), no solo a
          normal/vip.
Feature 2 (aviso al representante) — al decidir un KYB de EMPRESA se envía además
          un correo company-aware; una verificación individual NO lo dispara.
"""
import uuid

import pytest

from db_client import db
from auth_utils import normalize_phone, SENSITIVE_USER_FIELDS
import routes.blocklist as bl
import routes.kyc as kyc_routes

pytestmark = pytest.mark.asyncio

ADMIN = {"user_id": "audit_ebec943_admin", "role": "admin", "email": "admin@rb.com"}


class _Req:
    """Request mínimo para invocar los handlers sin el stack HTTP."""
    def __init__(self, body=None):
        self._body = body or {}
        self.headers = {"content-type": "application/json"}

    async def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _bypass_staff(monkeypatch):
    async def _rs(_request):
        return dict(ADMIN)

    async def _can(_actor):
        return None

    async def _totp(_user, _code, action_label=""):
        return None

    monkeypatch.setattr(bl, "require_staff", _rs)
    monkeypatch.setattr(bl, "_assert_can_manage_blocklist", _can)
    monkeypatch.setattr(bl, "_enforce_totp_step_up", _totp)
    yield


def _assert_no_credentials(user: dict):
    assert user is not None
    for f in SENSITIVE_USER_FIELDS:
        assert f not in user, f"El campo sensible {f!r} NO debe salir en la respuesta"
    # La información administrativa necesaria SÍ se conserva.
    assert "email" in user and "phone" in user


# ============================================================
# EMP-A02 — sin fuga de credenciales en verify/reject phone
# ============================================================

async def _seed_user(uid, **extra):
    doc = {
        "user_id": uid, "role": "normal", "email": f"{uid}@rb.com",
        "phone": normalize_phone("+5355500001"),
        "account_status": "under_review", "phone_verified": False,
        "email_verified": True,
        # credenciales que NUNCA deben salir
        "password_hash": "$2b$12$FAKEHASHFAKEHASHFAKEHASH",
        "verification_token": "tok_SECRET_123",
        "totp_secret_encrypted": "enc_SECRET",
        "password_reset_token_hash": "rh_SECRET",
    }
    doc.update(extra)
    await db.users.delete_one({"user_id": uid})
    await db.users.insert_one(doc)
    return uid


async def test_empa02_verify_phone_strips_credentials():
    uid = f"a02v_{uuid.uuid4().hex[:8]}"
    await _seed_user(uid, phone=normalize_phone(f"+535550{uuid.uuid4().int % 90000 + 10000}"))
    try:
        res = await bl.admin_verify_user_phone(uid, _Req({}))
        assert res["ok"] is True and res["already_verified"] is False
        _assert_no_credentials(res["user"])
    finally:
        await db.users.delete_one({"user_id": uid})
        await db.notifications.delete_many({"recipient_user_id": uid})
        await db.audit_logs.delete_many({"entity_id": uid})


async def test_empa02_already_verified_branch_strips_credentials():
    uid = f"a02a_{uuid.uuid4().hex[:8]}"
    await _seed_user(uid, phone=normalize_phone(f"+535551{uuid.uuid4().int % 90000 + 10000}"),
                     account_status="active", phone_verified=True)
    try:
        res = await bl.admin_verify_user_phone(uid, _Req({}))
        assert res["already_verified"] is True
        _assert_no_credentials(res["user"])
    finally:
        await db.users.delete_one({"user_id": uid})


async def test_empa02_reject_phone_strips_credentials():
    uid = f"a02r_{uuid.uuid4().hex[:8]}"
    phone = normalize_phone(f"+535552{uuid.uuid4().int % 90000 + 10000}")
    await _seed_user(uid, phone=phone)
    try:
        res = await bl.admin_reject_user_phone(
            uid, bl.RejectPhonePayload(reason="documento falso"), _Req({}))
        assert res["ok"] is True
        _assert_no_credentials(res["user"])
    finally:
        await db.users.delete_one({"user_id": uid})
        await db.blocked_contacts.delete_many({"phone": phone})
        await db.notifications.delete_many({"recipient_user_id": uid})
        await db.audit_logs.delete_many({"entity_id": uid})


# ============================================================
# EMP-A03 — el bloqueo masivo suspende también a EMPRESA
# ============================================================

async def test_empa03_bulk_import_suspends_empresa_too():
    tag = uuid.uuid4().int
    p_emp = normalize_phone(f"+535561{tag % 90000 + 10000}")
    p_nrm = normalize_phone(f"+535562{tag % 90000 + 10000}")
    emp = f"a03emp_{uuid.uuid4().hex[:8]}"
    nrm = f"a03nrm_{uuid.uuid4().hex[:8]}"
    await db.users.delete_many({"user_id": {"$in": [emp, nrm]}})
    await db.users.insert_many([
        {"user_id": emp, "role": "empresa", "email": f"{emp}@rb.com", "phone": p_emp,
         "account_status": "active", "phone_verified": True},
        {"user_id": nrm, "role": "normal", "email": f"{nrm}@rb.com", "phone": p_nrm,
         "account_status": "active", "phone_verified": True},
    ])
    text = f"Empresa Mala\n{p_emp}\n\nNormal Malo\n{p_nrm}\n"
    try:
        res = await bl.bulk_import_blocked_contacts(bl.BulkImportPayload(text=text), _Req({}))
        assert res["ok"] is True and res["affected_active_accounts"] >= 2
        emp_u = await db.users.find_one({"user_id": emp}, {"_id": 0})
        nrm_u = await db.users.find_one({"user_id": nrm}, {"_id": 0})
        # EMP-A03: la EMPRESA también pasa a revisión y pierde phone_verified.
        assert emp_u["account_status"] == "under_review" and emp_u["phone_verified"] is False
        assert nrm_u["account_status"] == "under_review" and nrm_u["phone_verified"] is False
    finally:
        await db.users.delete_many({"user_id": {"$in": [emp, nrm]}})
        await db.blocked_contacts.delete_many({"phone": {"$in": [p_emp, p_nrm]}})
        await db.audit_logs.delete_many({"action": "blocked_contact.bulk_import"})


# ============================================================
# Feature 2 — aviso por EMAIL al representante en decisiones de KYB de empresa
# ============================================================

async def test_feature2_company_kyb_decision_emails_the_representative(monkeypatch):
    uid = f"kyb_{uuid.uuid4().hex[:8]}"
    await db.users.delete_one({"user_id": uid})
    await db.users.insert_one({
        "user_id": uid, "role": "empresa", "email": f"{uid}@rb.com",
        "name": "KYB Repr SA", "preferred_language": "es"})
    calls = []
    import email_service
    monkeypatch.setattr(email_service, "notify_company_kyb_approved",
                        lambda *a, **k: calls.append(("approved", a, k)) or True)
    monkeypatch.setattr(email_service, "notify_company_kyb_rejected",
                        lambda *a, **k: calls.append(("rejected", a, k)) or True)
    monkeypatch.setattr(email_service, "notify_company_kyb_needs_info",
                        lambda *a, **k: calls.append(("needs_info", a, k)) or True)
    try:
        # Verificación de EMPRESA → dispara el correo correspondiente, con motivo.
        await kyc_routes._maybe_email_company_kyb(
            {"user_id": uid, "kind": "company"}, "approved")
        await kyc_routes._maybe_email_company_kyb(
            {"user_id": uid, "kind": "company"}, "rejected", "documento ilegible")
        await kyc_routes._maybe_email_company_kyb(
            {"user_id": uid, "kind": "company"}, "needs_info", "falta la licencia")
        kinds = [c[0] for c in calls]
        assert kinds == ["approved", "rejected", "needs_info"]
        # El destinatario es el email de la empresa y el motivo viaja en el correo.
        assert calls[0][1][0] == f"{uid}@rb.com"
        assert "documento ilegible" in calls[1][1]
        assert "falta la licencia" in calls[2][1]

        # Una verificación INDIVIDUAL NO dispara el correo de empresa.
        calls.clear()
        await kyc_routes._maybe_email_company_kyb(
            {"user_id": uid, "kind": "individual"}, "approved")
        await kyc_routes._maybe_email_company_kyb(
            {"user_id": uid}, "approved")  # sin kind → tampoco
        assert calls == []
    finally:
        await db.users.delete_one({"user_id": uid})
