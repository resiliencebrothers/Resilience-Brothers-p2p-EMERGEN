"""A02 — RECHAZAR no debe sobrescribir una APROBACIÓN que ya creó la cuenta.

Reproduce la CARRERA in-process: el revisor A inicia el rechazo y lee
status=pending; ANTES de su escritura, el revisor B completa la aprobación
(solicitud→approved + cuenta Empresa under_review creada). Cuando A reanuda, su
transición CAS condicionada a `pending` ya no coincide → 409, SIN pisar el
estado ni crear/0 notificar éxito. Solo una decisión gana.
"""
import uuid

import pytest
from fastapi import HTTPException

from db_client import db
from auth_utils import now_utc, iso, _hash_password
from routes import company_requests as cr
from routes.company_requests import CompanyRequestReject

pytestmark = pytest.mark.asyncio

REQUESTER = "user_test_vip01"


async def _seed_pending():
    rid = f"coreq_{uuid.uuid4().hex[:12]}"
    email = f"empresa_{uuid.uuid4().hex[:10]}@mibodega.com"
    phone = "+1" + "".join(str(int(c, 16) % 10) for c in uuid.uuid4().hex[:10])
    now = iso(now_utc())
    await db.company_requests.insert_one({
        "id": rid, "user_id": REQUESTER, "user_email": "vip.test@resilience.com",
        "user_name": "VIP", "company_name": "Carrera S.A.", "account_email": email,
        "company_phone": phone, "tax_id": "RNC-A02", "address": "Calle A02 #1",
        "password_hash": _hash_password("CompanyPass123!"), "status": "pending",
        "created_at": now, "updated_at": now, "reviewed_by": None,
        "reviewed_at": None, "admin_note": None, "new_user_id": None,
    })
    return rid, email, phone


async def _cleanup(rid, email):
    await db.company_requests.delete_many({"id": rid})
    await db.users.delete_many({"email": email})
    await db.notifications.delete_many(
        {"recipient_user_id": REQUESTER,
         "type": {"$in": ["company_request_approved", "company_request_rejected"]}})


async def _fake_perm(request, perm):
    return {"user_id": "user_test_admin01", "role": "admin"}


async def test_a02_reject_loses_to_concurrent_approval(monkeypatch):
    rid, email, _ = await _seed_pending()
    try:
        monkeypatch.setattr(cr, "require_permission", _fake_perm)
        real_db = cr.db
        state = {"fired": False}

        class _CReq:
            def __getattr__(self, n):
                return getattr(real_db.company_requests, n)

            async def update_one(self, flt, update, *a, **k):
                # Intercepta SOLO la escritura de rechazo (status→rejected):
                # justo ANTES, el revisor B completa la APROBACIÓN entera.
                if (not state["fired"] and isinstance(update, dict)
                        and update.get("$set", {}).get("status") == "rejected"):
                    state["fired"] = True
                    await cr.admin_approve_company_request(rid, None)
                return await real_db.company_requests.update_one(flt, update, *a, **k)

        creq = _CReq()

        class _Db:
            def __getattr__(self, n):
                if n == "company_requests":
                    return creq
                return getattr(real_db, n)

        monkeypatch.setattr(cr, "db", _Db())

        # A reanuda el rechazo con lectura antigua 'pending' → debe PERDER (409).
        with pytest.raises(HTTPException) as ei:
            await cr.admin_reject_company_request(
                rid, CompanyRequestReject(admin_note="motivo"), None)
        assert ei.value.status_code == 409
        monkeypatch.undo()

        # GANA la aprobación: estado approved + cuenta Empresa creada e intacta.
        fresh = await real_db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh["status"] == "approved"
        assert fresh["new_user_id"]
        acc = await real_db.users.find_one({"user_id": fresh["new_user_id"]})
        assert acc is not None
        assert acc["account_status"] == "under_review"
        assert acc["email"] == email
    finally:
        monkeypatch.undo()
        await _cleanup(rid, email)


async def test_a02_approve_loses_to_concurrent_rejection(monkeypatch):
    rid, email, _ = await _seed_pending()
    try:
        monkeypatch.setattr(cr, "require_permission", _fake_perm)
        real_db = cr.db
        state = {"fired": False}

        class _CReq:
            def __getattr__(self, n):
                return getattr(real_db.company_requests, n)

            async def update_one(self, flt, update, *a, **k):
                # Intercepta la CAS de aprobación (status→approved): justo ANTES,
                # el revisor B completa el RECHAZO entero.
                if (not state["fired"] and isinstance(update, dict)
                        and update.get("$set", {}).get("status") == "approved"):
                    state["fired"] = True
                    await cr.admin_reject_company_request(
                        rid, CompanyRequestReject(admin_note="rechazo gana"), None)
                return await real_db.company_requests.update_one(flt, update, *a, **k)

        creq = _CReq()

        class _Db:
            def __getattr__(self, n):
                if n == "company_requests":
                    return creq
                return getattr(real_db, n)

        monkeypatch.setattr(cr, "db", _Db())

        # A reanuda la aprobación con lectura antigua → debe PERDER (409) y NO
        # crear la cuenta (la CAS falla ANTES del insert).
        with pytest.raises(HTTPException) as ei:
            await cr.admin_approve_company_request(rid, None)
        assert ei.value.status_code == 409
        monkeypatch.undo()

        fresh = await real_db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh["status"] == "rejected"
        assert not fresh.get("new_user_id")
        # NINGUNA cuenta Empresa creada por el aprobador con lectura antigua.
        assert await real_db.users.find_one({"email": email}) is None
    finally:
        monkeypatch.undo()
        await _cleanup(rid, email)
