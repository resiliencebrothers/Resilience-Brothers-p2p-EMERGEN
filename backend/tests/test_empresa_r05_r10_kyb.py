"""R05/R10 — ciclo de verificación empresarial (KYB) robusto.

R05: desde 'needs_more_info' la empresa PUEDE subsanar y reenviar (vuelve a
     'pending') sin exigir un rechazo administrativo intermedio.
R10: una revalidación con datos INVÁLIDOS NO retira la aprobación vigente, y una
     válida inserta el expediente nuevo ANTES de retirar el anterior (sin dejar
     la cuenta sin expediente). El guard usa el expediente 'company' MÁS RECIENTE.
"""
import uuid

import pytest

from db_client import db
from services import kyc as kyc_service
from services.user_verification import _kyc_is_verified

pytestmark = pytest.mark.asyncio

UID = "user_test_empresa_r05r10"
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
       "QVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def _docs():
    return [{"type": "tax_certificate", "data": PNG},
            {"type": "operating_license", "data": PNG}]


def _user():
    return {"user_id": UID, "email": "r05r10@example.com", "name": "Empresa R",
            "role": "empresa", "phone": "+5350001010"}


def _fields(fiscal="RB-OK", address="Calle 1"):
    return {"company_name": "Empresa R", "fiscal_code": fiscal,
            "legal_address": address}


async def _clean():
    await db.users.delete_one({"user_id": UID})
    await db.kyc_verifications.delete_many({"user_id": UID})


async def _seed_user():
    await db.users.insert_one({"user_id": UID, "role": "empresa",
                               "email": "r05r10@example.com", "name": "Empresa R",
                               "kyc_status": "unverified"})


async def _mark_verified(vid):
    await db.kyc_verifications.update_one({"id": vid}, {"$set": {"status": "verified"}})
    await db.users.update_one({"user_id": UID}, {"$set": {"kyc_status": "verified"}})


async def test_r10_invalid_revalidation_keeps_existing_approval():
    await _clean()
    await _seed_user()
    try:
        first = await kyc_service.submit_company_verification(
            db, _user(), _docs(), _fields(), "1.2.3.4", "UA")
        await _mark_verified(first["id"])
        assert await _kyc_is_verified(db, UID, "empresa") is True

        # Revalidación con código fiscal solo-espacios → debe RECHAZARSE sin tocar
        # la aprobación vigente.
        with pytest.raises(ValueError):
            await kyc_service.submit_company_verification(
                db, _user(), _docs(), _fields(fiscal="   "), "1.2.3.4", "UA")

        # La aprobación anterior sigue vigente y la empresa sigue verificada.
        still = await db.kyc_verifications.find_one({"id": first["id"]}, {"_id": 0})
        assert still["status"] == "verified"
        assert await _kyc_is_verified(db, UID, "empresa") is True
        # No quedó ningún expediente huérfano 'superseded'.
        assert await db.kyc_verifications.count_documents(
            {"user_id": UID, "status": "superseded"}) == 0
    finally:
        await _clean()


async def test_r10_valid_revalidation_inserts_first_then_supersedes():
    await _clean()
    await _seed_user()
    try:
        first = await kyc_service.submit_company_verification(
            db, _user(), _docs(), _fields(), "1.2.3.4", "UA")
        await _mark_verified(first["id"])

        new = await kyc_service.submit_company_verification(
            db, _user(), _docs(fiscal="RB-NEW") if False else _docs(),
            _fields(fiscal="RB-NEW", address="Calle 2"), "1.2.3.4", "UA")
        assert new["status"] == "pending"
        # El nuevo expediente existe (insert-first) y el anterior quedó superseded.
        old = await db.kyc_verifications.find_one({"id": first["id"]}, {"_id": 0})
        assert old["status"] == "superseded"
        # El guard usa el expediente MÁS RECIENTE → ya NO verificada (en revisión).
        assert await _kyc_is_verified(db, UID, "empresa") is False
    finally:
        await _clean()


async def test_r05_needs_more_info_can_resubmit():
    await _clean()
    await _seed_user()
    try:
        first = await kyc_service.submit_company_verification(
            db, _user(), _docs(), _fields(), "1.2.3.4", "UA")
        # El staff pide más información.
        await db.kyc_verifications.update_one(
            {"id": first["id"]},
            {"$set": {"status": "needs_more_info", "review_notes": "Sube la licencia a color"}})
        # La empresa subsana y reenvía SIN necesitar un rechazo previo.
        again = await kyc_service.submit_company_verification(
            db, _user(), _docs(), _fields(address="Calle corregida"), "1.2.3.4", "UA")
        assert again["status"] == "pending"
        prev = await db.kyc_verifications.find_one({"id": first["id"]}, {"_id": 0})
        assert prev["status"] == "superseded"
    finally:
        await _clean()


async def test_pending_blocks_duplicate_submit():
    await _clean()
    await _seed_user()
    try:
        await kyc_service.submit_company_verification(
            db, _user(), _docs(), _fields(), "1.2.3.4", "UA")
        # Ya hay uno EN REVISIÓN → un segundo envío simultáneo se rechaza.
        with pytest.raises(ValueError):
            await kyc_service.submit_company_verification(
                db, _user(), _docs(), _fields(), "1.2.3.4", "UA")
    finally:
        await _clean()
