"""EMP-A04 (idempotencia del aviso al cliente ante interrupción).

El reparto de avisos de una aprobación de Empresa guarda el aviso persistente
(campana) y, en una escritura SEPARADA, marca el canal `client` como completado.
Una caída ENTRE ambas escrituras dejaba al recuperador re-ejecutar el canal y,
como `_insert_notification` generaba un id nuevo en cada llamada sin clave de
deduplicación, creaba un SEGUNDO aviso para la misma (solicitud, decisión,
destinatario).

Esta regresión reproduce esa interrupción (se simula la marca de canal perdida)
y exige que, tras la recuperación, exista EXACTAMENTE UN aviso persistente para
el destinatario. El control negativo (quitar `dedup_key`) produciría dos.
"""
import uuid

import pytest

from db_client import db
from auth_utils import now_utc, iso
import routes.company_requests as cr

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_push_no_email(monkeypatch):
    async def _push(*_a, **_k):
        return None

    import push_service
    import routes.notifications as notif
    import email_service
    monkeypatch.setattr(push_service, "send_push_to_user", _push)
    monkeypatch.setattr(notif, "send_push_to_user", _push)
    # El correo de verificación "se envía" con éxito para que el canal selle.
    monkeypatch.setattr(email_service, "notify_email_verification",
                        lambda *a, **k: True)
    yield


async def _seed_approved_request():
    rid = f"a04req_{uuid.uuid4().hex[:8]}"
    requester = f"a04usr_{uuid.uuid4().hex[:8]}"
    new_uid = f"a04emp_{uuid.uuid4().hex[:8]}"
    await db.users.insert_one({
        "user_id": new_uid, "role": "empresa", "email": f"{new_uid}@rb.com",
        "name": "Empresa A04", "preferred_language": "es",
        "verification_token": uuid.uuid4().hex, "parent_user_id": requester})
    await db.company_requests.insert_one({
        "id": rid, "user_id": requester, "new_user_id": new_uid,
        "status": "approved", "company_name": "Empresa A04 SA",
        "reviewed_by": "a04_staff", "created_at": iso(now_utc())})
    return rid, requester, new_uid


async def _client_notif_count(requester: str) -> int:
    return await db.notifications.count_documents(
        {"recipient_user_id": requester, "type": "company_request_approved"})


async def test_recovery_after_lost_channel_seal_does_not_duplicate_client_notice():
    rid, requester, new_uid = await _seed_approved_request()
    try:
        # 1) Primera pasada completa de avisos.
        await cr._finalize_company_approval(rid)
        assert await _client_notif_count(requester) == 1
        doc = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert doc.get("notified_at")  # selló al completar todos los canales
        assert "client" in (doc.get("notify_channels") or [])

        # 2) Simular la INTERRUPCIÓN: el aviso se guardó pero la marca de canal
        #    y la confirmación final se perdieron (crash entre ambas escrituras).
        await db.company_requests.update_one(
            {"id": rid},
            {"$pull": {"notify_channels": "client"},
             "$unset": {"notified_at": "", "notify_claimed_at": ""}})

        # 3) El recuperador re-ejecuta el canal `client`.
        await cr._finalize_company_approval(rid)

        # 4) Idempotente: sigue habiendo UN solo aviso y el canal vuelve a sellar.
        assert await _client_notif_count(requester) == 1
        doc2 = await db.company_requests.find_one({"id": rid}, {"_id": 0})
        assert "client" in (doc2.get("notify_channels") or [])
        assert doc2.get("notified_at")
    finally:
        await db.users.delete_one({"user_id": new_uid})
        await db.company_requests.delete_one({"id": rid})
        await db.notifications.delete_many({"recipient_user_id": requester})
        await db.audit_logs.delete_many({"entity_id": rid})


async def test_direct_double_call_is_idempotent_per_request_decision_recipient():
    """Dos llamadas directas al aviso del cliente (mismo request+decisión) crean
    un único documento persistente — base de la garantía 'exactamente uno'."""
    rid = f"a04dir_{uuid.uuid4().hex[:8]}"
    requester = f"a04dusr_{uuid.uuid4().hex[:8]}"
    req = {"id": rid, "user_id": requester, "account_email": "x@rb.com"}
    try:
        await cr._notify_client_decision(req, approved=True)
        await cr._notify_client_decision(req, approved=True)
        assert await _client_notif_count(requester) == 1
        n = await db.notifications.find_one(
            {"recipient_user_id": requester, "type": "company_request_approved"},
            {"_id": 0, "dedup_key": 1})
        assert n and n.get("dedup_key") == f"company-decision:{rid}:approved:{requester}"
    finally:
        await db.notifications.delete_many({"recipient_user_id": requester})
