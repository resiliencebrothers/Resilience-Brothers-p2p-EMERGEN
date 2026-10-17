"""A02 — RECHAZAR no debe sobrescribir una APROBACIÓN que ya creó la cuenta.

Reproduce la CARRERA in-process: el revisor A inicia el rechazo y lee
status=pending; ANTES de su escritura, el revisor B completa la aprobación
(solicitud→approved + cuenta Empresa under_review creada). Cuando A reanuda, su
transición CAS condicionada a `pending` ya no coincide → 409, SIN pisar el
estado ni crear/0 notificar éxito. Solo una decisión gana.
"""
import uuid
import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import now_utc, iso, _hash_password
from routes import company_requests as cr
from routes.company_requests import CompanyRequestReject

pytestmark = pytest.mark.asyncio

REQUESTER = "user_test_vip01"


@pytest.fixture(autouse=True)
def _stub_verification_email(monkeypatch):
    """Hermético + determinista: el correo de verificación NO golpea Resend en
    los tests y devuelve éxito (True) por defecto, así el canal 'email' sella
    como en producción cuando el envío funciona. Los tests que necesitan simular
    un FALLO de correo (P02-R) sobreescriben este stub con su propio monkeypatch
    (aplicado después → gana)."""
    import email_service
    monkeypatch.setattr(email_service, "notify_email_verification", lambda *a, **k: True)
    yield


class _Kill(BaseException):
    """Simula terminación del proceso: NO la captura ningún `except Exception`."""


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
    await db.users.delete_many({"$or": [{"email": email}, {"parent_user_id": REQUESTER}]})
    await db.notifications.delete_many(
        {"recipient_user_id": REQUESTER,
         "type": {"$in": ["company_request_approved", "company_request_rejected",
                          "company_account_activated", "new_company_request"]}})


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
                # Intercepta la CAS de CLAIM (status→approving): justo ANTES,
                # el revisor B completa el RECHAZO entero.
                if (not state["fired"] and isinstance(update, dict)
                        and update.get("$set", {}).get("status") == "approving"):
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


# ────────────────────────────────────────────────────────── A03 crash-safety

async def _seed_approving(reviewed_at, with_account=False):
    """Siembra una solicitud ya reclamada ('approving') con identidad estable."""
    rid = f"coreq_{uuid.uuid4().hex[:12]}"
    new_uid = f"coacct_{uuid.uuid4().hex[:12]}"
    email = f"empresa_{uuid.uuid4().hex[:10]}@mibodega.com"
    phone = "+1" + "".join(str(int(c, 16) % 10) for c in uuid.uuid4().hex[:10])
    now = iso(now_utc())
    await db.company_requests.insert_one({
        "id": rid, "user_id": REQUESTER, "user_email": "vip.test@resilience.com",
        "user_name": "VIP", "company_name": "Reanudable S.A.", "account_email": email,
        "company_phone": phone, "tax_id": "RNC-A03", "address": "Calle A03 #1",
        "password_hash": _hash_password("CompanyPass123!"), "status": "approving",
        "created_at": now, "updated_at": now, "reviewed_by": "user_test_admin01",
        "reviewed_at": reviewed_at, "admin_note": None, "new_user_id": new_uid,
    })
    if with_account:
        await db.users.insert_one(cr._build_company_user_doc(
            await db.company_requests.find_one({"id": rid}, {"_id": 0}), new_uid, "es"))
    return rid, new_uid, email


async def test_a03_crash_before_insert_is_recoverable(monkeypatch):
    rid, email, _ = await _seed_pending()
    try:
        monkeypatch.setattr(cr, "require_permission", _fake_perm)
        real_db = cr.db
        boom = {"armed": True}

        class _Users:
            def __getattr__(self, n):
                return getattr(real_db.users, n)

            async def update_one(self, *a, **k):
                if boom["armed"]:           # la 1ª escritura de users = upsert de la cuenta
                    boom["armed"] = False
                    raise _Kill("process killed mid-insert")
                return await real_db.users.update_one(*a, **k)

        users_proxy = _Users()

        class _Db:
            def __getattr__(self, n):
                if n == "users":
                    return users_proxy
                return getattr(real_db, n)

        monkeypatch.setattr(cr, "db", _Db())
        with pytest.raises(_Kill):
            await cr.admin_approve_company_request(rid, None)
        monkeypatch.undo()

        # Estado RECUPERABLE: 'approving' con new_user_id pero SIN cuenta fantasma.
        mid = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert mid["status"] == "approving"
        assert mid["new_user_id"]
        assert await db.users.find_one({"user_id": mid["new_user_id"]}) is None

        # Reintento del endpoint → completa idempotentemente (una sola cuenta).
        monkeypatch.setattr(cr, "require_permission", _fake_perm)
        fresh = await cr.admin_approve_company_request(rid, None)
        assert fresh["status"] == "approved"
        acc = await db.users.find_one({"user_id": fresh["new_user_id"]})
        assert acc and acc["account_status"] == "under_review" and acc["email"] == email
        assert await db.users.count_documents({"email": email}) == 1
        assert "password_hash" not in fresh
    finally:
        monkeypatch.undo()
        await _cleanup(rid, email)


async def test_a03_crash_before_seal_is_recoverable(monkeypatch):
    rid, email, _ = await _seed_pending()
    try:
        monkeypatch.setattr(cr, "require_permission", _fake_perm)
        real_db = cr.db
        boom = {"armed": True}

        class _CReq:
            def __getattr__(self, n):
                return getattr(real_db.company_requests, n)

            async def update_one(self, flt, update, *a, **k):
                # Muere JUSTO en el sellado approving→approved (cuenta ya creada).
                if (boom["armed"] and isinstance(update, dict)
                        and update.get("$set", {}).get("status") == "approved"):
                    boom["armed"] = False
                    raise _Kill("process killed before seal")
                return await real_db.company_requests.update_one(flt, update, *a, **k)

        creq = _CReq()

        class _Db:
            def __getattr__(self, n):
                if n == "company_requests":
                    return creq
                return getattr(real_db, n)

        monkeypatch.setattr(cr, "db", _Db())
        with pytest.raises(_Kill):
            await cr.admin_approve_company_request(rid, None)
        monkeypatch.undo()

        # La cuenta YA existe pero la solicitud quedó 'approving' (sin sellar).
        mid = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert mid["status"] == "approving"
        assert await db.users.find_one({"user_id": mid["new_user_id"]}) is not None

        # Reintento → sella sin duplicar la cuenta.
        monkeypatch.setattr(cr, "require_permission", _fake_perm)
        fresh = await cr.admin_approve_company_request(rid, None)
        assert fresh["status"] == "approved"
        assert await db.users.count_documents({"email": email}) == 1
    finally:
        monkeypatch.undo()
        await _cleanup(rid, email)


async def test_a03_recoverer_completes_stuck_approving():
    # reviewed_at 5 min atrás → supera el cutoff de 120s del recuperador.
    reviewed = iso(now_utc() - timedelta(minutes=5))
    rid, new_uid, email = await _seed_approving(reviewed, with_account=False)
    try:
        healed = await cr.recover_company_approvals()
        assert healed >= 1
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh["status"] == "approved"
        assert fresh.get("notified_at")
        acc = await db.users.find_one({"user_id": new_uid})
        assert acc and acc["account_status"] == "under_review"
        assert await db.users.count_documents({"email": email}) == 1
        assert "password_hash" not in fresh
    finally:
        await _cleanup(rid, email)


async def test_a03_recoverer_finalizes_pending_notifications():
    reviewed = iso(now_utc() - timedelta(minutes=5))
    rid, new_uid, email = await _seed_approving(reviewed, with_account=True)
    # Simula: cuenta creada y sellada, pero el proceso murió antes de notificar.
    await db.company_requests.update_one(
        {"id": rid}, {"$set": {"status": "approved"}, "$unset": {"password_hash": ""}})
    try:
        await cr.recover_company_approvals()
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("notified_at")
        note = await db.notifications.find_one(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"})
        assert note is not None
        # No duplica la cuenta.
        assert await db.users.count_documents({"user_id": new_uid}) == 1
    finally:
        await _cleanup(rid, email)


async def test_a03_concurrent_complete_creates_single_account():
    reviewed = iso(now_utc() - timedelta(minutes=5))
    rid, new_uid, email = await _seed_approving(reviewed, with_account=False)
    try:
        # Dos completadores concurrentes (p. ej. reintento + recuperador) →
        # identidad estable + índice único garantizan UNA sola cuenta.
        await asyncio.gather(
            cr._complete_company_approval(rid, "user_test_admin01"),
            cr._complete_company_approval(rid, None),
            return_exceptions=True,
        )
        assert await db.users.count_documents({"user_id": new_uid}) == 1
        assert await db.users.count_documents({"email": email}) == 1
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh["status"] == "approved"
        # Aviso enviado exactamente una vez.
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 1
    finally:
        await _cleanup(rid, email)


# ============================================================
# A04 — DOS ENVÍOS SIMULTÁNEOS NO PUEDEN CREAR DOS PENDIENTES
# ============================================================

def _pending_doc(uid):
    rid = f"coreq_{uuid.uuid4().hex[:12]}"
    email = f"empresa_{uuid.uuid4().hex[:10]}@mibodega.com"
    phone = "+1" + "".join(str(int(c, 16) % 10) for c in uuid.uuid4().hex[:10])
    now = iso(now_utc())
    return {
        "id": rid, "user_id": uid, "user_email": "a04.test@resilience.com",
        "user_name": "A04", "company_name": "Carrera A04 S.A.", "account_email": email,
        "company_phone": phone, "tax_id": "RNC-A04", "address": "Calle A04 #1",
        "password_hash": _hash_password("CompanyPass123!"), "status": "pending",
        "created_at": now, "updated_at": now, "reviewed_by": None,
        "reviewed_at": None, "admin_note": None, "new_user_id": None,
    }


async def test_a04_concurrent_inserts_keep_single_pending():
    """Dos POST concurrentes del mismo usuario: el índice único parcial deja
    pasar UNA sola pendiente; el otro recibe DuplicateKeyError (→409 en el
    endpoint). Tras resolver (rechazo), puede volver a solicitar."""
    await cr.ensure_indexes()  # garantiza el índice único parcial
    uid = f"user_a04_{uuid.uuid4().hex[:8]}"
    try:
        results = await asyncio.gather(
            db.company_requests.insert_one(_pending_doc(uid)),
            db.company_requests.insert_one(_pending_doc(uid)),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        assert len(errors) == 1
        assert isinstance(errors[0], DuplicateKeyError)
        assert await db.company_requests.count_documents(
            {"user_id": uid, "status": "pending"}) == 1

        # Resuelta (rechazada) → ya no cuenta para el índice parcial → re-solicitar OK.
        await db.company_requests.update_many(
            {"user_id": uid, "status": "pending"}, {"$set": {"status": "rejected"}})
        await db.company_requests.insert_one(_pending_doc(uid))
        assert await db.company_requests.count_documents(
            {"user_id": uid, "status": "pending"}) == 1
    finally:
        await db.company_requests.delete_many({"user_id": uid})


async def test_a04_dedup_resolves_existing_duplicates_before_index():
    """El pre-paso de dedup colapsa pendientes duplicadas preexistentes a UNA
    (la más reciente) para que la creación del índice único parcial no falle."""
    uid = f"user_a04dup_{uuid.uuid4().hex[:8]}"
    try:
        # Simula duplicados anteriores al índice: se insertan SIN el guard.
        await db.company_requests.drop_index("uniq_company_request_pending_user")
        d1 = _pending_doc(uid)
        d1["created_at"] = iso(now_utc())
        d2 = _pending_doc(uid)
        d2["created_at"] = iso(now_utc())
        await db.company_requests.insert_one(d1)
        await db.company_requests.insert_one(d2)
        assert await db.company_requests.count_documents(
            {"user_id": uid, "status": "pending"}) == 2

        await cr._dedup_pending_requests()
        assert await db.company_requests.count_documents(
            {"user_id": uid, "status": "pending"}) == 1
        # El índice vuelve a crearse sin error tras el dedup.
        await cr.ensure_indexes()
        info = await db.company_requests.index_information()
        assert "uniq_company_request_pending_user" in info
    finally:
        await db.company_requests.delete_many({"user_id": uid})
        await cr.ensure_indexes()



# ============================================================
# P02 — AVISOS SELLADOS ANTES DE ENVIARSE DEBEN RECUPERARSE
# El bug: `notified_at` se escribía como RECLAMO (antes de enviar). Un proceso
# muerto tras ese marcador quedaba fuera del recuperador para siempre. Ahora el
# reclamo es un LEASE recuperable (`notify_claimed_at`) y `notified_at` es la
# CONFIRMACIÓN final, sellada solo tras completar todos los canales; cada canal
# se marca en `notify_channels` para no reenviarse (idempotencia por canal).
# ============================================================

async def _seed_approved_unnotified():
    """Solicitud 'approved' con cuenta creada, SIN avisos finalizados."""
    reviewed = iso(now_utc() - timedelta(minutes=5))
    rid, new_uid, email = await _seed_approving(reviewed, with_account=True)
    await db.company_requests.update_one(
        {"id": rid}, {"$set": {"status": "approved"}, "$unset": {"password_hash": ""}})
    return rid, new_uid, email


async def test_p02_crash_after_claim_is_still_recoverable(monkeypatch):
    """Muerte del proceso DESPUÉS del reclamo del lease y ANTES de enviar: el
    registro NO queda excluido para siempre; el recuperador lo completa."""
    rid, new_uid, email = await _seed_approved_unnotified()
    try:
        def _kill(*a, **k):
            raise _Kill("process killed mid-notify (antes del primer canal)")

        # El PRIMER canal persistente ('audit' = log_action) muere con BaseException.
        monkeypatch.setattr(cr, "log_action", _kill)
        with pytest.raises(_Kill):
            await cr._finalize_company_approval(rid)
        monkeypatch.undo()

        # Lease reclamado pero SIN confirmación: aún recuperable (notified_at falta).
        mid = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert mid.get("notify_claimed_at")
        assert not mid.get("notified_at")
        assert not mid.get("notify_channels")
        # NINGÚN aviso al cliente todavía.
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 0

        # "Reinicio": el lease expira (backdate) y el recuperador lo completa.
        await db.company_requests.update_one(
            {"id": rid}, {"$set": {"notify_claimed_at": iso(now_utc() - timedelta(minutes=5))}})
        await cr.recover_company_approvals()

        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("notified_at")
        assert set(fresh.get("notify_channels") or []) >= {"audit", "email", "staff", "client"}
        # Aviso al cliente entregado EXACTAMENTE una vez.
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 1
        assert await db.users.count_documents({"user_id": new_uid}) == 1
    finally:
        monkeypatch.undo()
        await _cleanup(rid, email)


async def test_p02_per_channel_idempotency_no_duplicate_resend(monkeypatch):
    """Recuperación de un aviso interrumpido a mitad: completa SOLO los canales
    faltantes sin reenviar los ya enviados (dedup por `notify_channels`)."""
    rid, new_uid, email = await _seed_approved_unnotified()
    try:
        # Simula: audit+email+staff ya enviados; solo falta 'client'. Lease viejo.
        await db.company_requests.update_one(
            {"id": rid}, {"$set": {
                "notify_channels": ["audit", "email", "staff"],
                "notify_claimed_at": iso(now_utc() - timedelta(minutes=5))}})
        calls = {"email": 0}

        import email_service

        def _count_email(*a, **k):
            calls["email"] += 1
        monkeypatch.setattr(email_service, "notify_email_verification", _count_email)

        await cr.recover_company_approvals()
        monkeypatch.undo()

        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert fresh.get("notified_at")
        assert set(fresh["notify_channels"]) >= {"audit", "email", "staff", "client"}
        # El correo NO se reenvió (ya estaba en notify_channels).
        assert calls["email"] == 0
        # El canal faltante 'client' se completó una sola vez.
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 1
    finally:
        monkeypatch.undo()
        await _cleanup(rid, email)


async def test_p02_fresh_lease_blocks_duplicate_worker():
    """Un lease VIVO (reciente) impide que un segundo ejecutor reenvíe: no hay
    confirmación ni avisos duplicados mientras el titular del lease trabaja."""
    rid, new_uid, email = await _seed_approved_unnotified()
    try:
        # Lease fresco (ahora mismo) tomado por otro ejecutor "vivo".
        await db.company_requests.update_one(
            {"id": rid}, {"$set": {"notify_claimed_at": iso(now_utc())}})
        # Un segundo intento NO debe reclamar ni enviar.
        await cr._finalize_company_approval(rid)
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert not fresh.get("notified_at")
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 0
    finally:
        await _cleanup(rid, email)



# ============================================================
# P02-R — UN CANAL NO SE SELLA SI SU ENVÍO FALLA (éxito explícito)
# El bug: `_run_channel` sellaba cualquier canal que no lanzara excepción. Pero
# (a) el correo devuelve un bool y `False` no se comprobaba; (b) el aviso al
# cliente absorbía errores de inserción y retornaba normal; (c) el fan-out al
# staff absorbía fallos por destinatario. Resultado: audit/email/staff/client se
# marcaban como completados y `notified_at` se sellaba aunque NO se entregaran,
# dejando al reconciliador sin nada que reintentar. Fix: resultado de éxito
# EXPLÍCITO por canal; no sellar en fallo; reintento idempotente por destinatario.
# ============================================================

async def _backdate_lease(rid):
    """Expira el lease para permitir que el recuperador vuelva a reclamar."""
    await db.company_requests.update_one(
        {"id": rid}, {"$set": {"notify_claimed_at": iso(now_utc() - timedelta(minutes=5))}})


async def test_p02r_email_false_does_not_seal_then_recovers(monkeypatch):
    """El correo devuelve False (envío fallido): el canal 'email' NO se sella y
    `notified_at` queda sin confirmar. Cuando el correo vuelve a funcionar, el
    recuperador completa SOLO 'email' y sella, sin reenviar los demás canales ni
    duplicar el aviso al cliente."""
    rid, new_uid, email = await _seed_approved_unnotified()
    try:
        import email_service
        state = {"ok": False}
        monkeypatch.setattr(email_service, "notify_email_verification",
                            lambda *a, **k: state["ok"])

        # 1ª pasada: email devuelve False.
        await cr._finalize_company_approval(rid)
        mid = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        chans = set(mid.get("notify_channels") or [])
        assert "email" not in chans, "email NO debe sellarse si el envío devolvió False"
        assert not mid.get("notified_at"), "no debe confirmarse con un canal pendiente"
        # Los canales persistentes que SÍ se entregaron quedaron sellados.
        assert {"audit", "client"}.issubset(chans)
        # Control: el aviso al cliente se entregó una vez pese al fallo del correo.
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 1

        # Recuperación: el correo ahora funciona.
        state["ok"] = True
        await _backdate_lease(rid)
        await cr.recover_company_approvals()
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert "email" in set(fresh.get("notify_channels") or [])
        assert fresh.get("notified_at"), "debe confirmar cuando todos los canales se completan"
        # El cliente NO fue notificado dos veces (dedup por canal).
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 1
    finally:
        monkeypatch.undo()
        await db.notifications.delete_many({"data.target_user_id": new_uid})
        await _cleanup(rid, email)


async def test_p02r_client_insert_error_absorbed_does_not_seal(monkeypatch):
    """Un error de inserción del aviso al cliente (absorbido en el helper) ya NO
    se trata como éxito: el canal 'client' no se sella y no hay confirmación.
    Al recuperarse, el aviso se entrega EXACTAMENTE una vez (sin duplicar)."""
    rid, new_uid, email = await _seed_approved_unnotified()
    try:
        import routes.notifications as notif
        orig_insert = notif._insert_notification
        state = {"fail_client": True}

        async def _insert_guard(**kw):
            if kw.get("type") == "company_request_approved" and state["fail_client"]:
                raise RuntimeError("DB caída al insertar el aviso del cliente")
            return await orig_insert(**kw)
        monkeypatch.setattr(notif, "_insert_notification", _insert_guard)

        await cr._finalize_company_approval(rid)
        mid = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert "client" not in set(mid.get("notify_channels") or [])
        assert not mid.get("notified_at")
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 0

        # Recuperación: la inserción del cliente ya funciona.
        state["fail_client"] = False
        await _backdate_lease(rid)
        await cr.recover_company_approvals()
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert "client" in set(fresh.get("notify_channels") or [])
        assert fresh.get("notified_at")
        assert await db.notifications.count_documents(
            {"recipient_user_id": REQUESTER, "type": "company_request_approved"}) == 1
    finally:
        monkeypatch.undo()
        await db.notifications.delete_many({"data.target_user_id": new_uid})
        await _cleanup(rid, email)


async def test_p02r_staff_partial_delivery_retries_only_failed(monkeypatch):
    """Entrega PARCIAL al personal: si la inserción a un destinatario falla, el
    canal 'staff' no se sella. Al recuperarse se reintenta SOLO al destinatario
    pendiente (idempotente por `target_user_id`): el que ya recibió el aviso no
    se duplica y, cuando todos lo tienen, el canal sella."""
    rid, new_uid, email = await _seed_approved_unnotified()
    s1 = f"staff_ok_{uuid.uuid4().hex[:8]}"
    s2 = f"staff_fail_{uuid.uuid4().hex[:8]}"
    await db.users.insert_many([
        {"user_id": s1, "role": "admin", "email": f"{s1}@resilience.com"},
        {"user_id": s2, "role": "admin", "email": f"{s2}@resilience.com"},
    ])
    try:
        import routes.notifications as notif
        orig_insert = notif._insert_notification
        state = {"fail_s2": True}

        async def _insert_guard(**kw):
            if (kw.get("type") == "new_user_pending"
                    and kw.get("recipient_user_id") == s2 and state["fail_s2"]):
                raise RuntimeError("broker de avisos caído para s2")
            return await orig_insert(**kw)
        monkeypatch.setattr(notif, "_insert_notification", _insert_guard)

        await cr._finalize_company_approval(rid)
        mid = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert "staff" not in set(mid.get("notify_channels") or []), \
            "staff NO debe sellarse con una entrega parcial"
        assert not mid.get("notified_at")
        # s1 recibió su aviso; s2 no.
        assert await db.notifications.count_documents(
            {"recipient_user_id": s1, "type": "new_user_pending",
             "data.target_user_id": new_uid}) == 1
        assert await db.notifications.count_documents(
            {"recipient_user_id": s2, "type": "new_user_pending",
             "data.target_user_id": new_uid}) == 0

        # Recuperación: s2 ya no falla.
        state["fail_s2"] = False
        await _backdate_lease(rid)
        await cr.recover_company_approvals()
        fresh = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert "staff" in set(fresh.get("notify_channels") or [])
        assert fresh.get("notified_at")
        # s1 NO duplicado (sigue en 1); s2 ahora entregado (1).
        assert await db.notifications.count_documents(
            {"recipient_user_id": s1, "type": "new_user_pending",
             "data.target_user_id": new_uid}) == 1
        assert await db.notifications.count_documents(
            {"recipient_user_id": s2, "type": "new_user_pending",
             "data.target_user_id": new_uid}) == 1
    finally:
        monkeypatch.undo()
        await db.users.delete_many({"user_id": {"$in": [s1, s2]}})
        await db.notifications.delete_many({"data.target_user_id": new_uid})
        await _cleanup(rid, email)
