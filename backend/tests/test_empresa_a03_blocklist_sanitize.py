"""EMP-A03 (saneamiento idempotente del conjunto histórico).

El importador masivo de bloqueos salta los teléfonos que YA existen en
`blocked_contacts` ("duplicados") y antes solo re-moderaba las cuentas cuyo
teléfono se acababa de insertar. Eso dejaba un hueco: una cuenta (p. ej. una
Empresa) que quedó ACTIVA con su teléfono ya bloqueado por una importación
anterior no se corregía al volver a importar ese mismo teléfono.

Esta regresión EMPIEZA desde «teléfono ya bloqueado + Empresa todavía activa»
y exige que una re-importación del mismo teléfono la pase a `under_review` y le
retire `phone_verified`. Incluye el control de no degradar una cuenta ya
`blocked` ni re-sellar el `under_review_since` de una ya en revisión.
"""
import uuid

import pytest

from db_client import db
from auth_utils import normalize_phone, now_utc, iso
import routes.blocklist as bl

pytestmark = pytest.mark.asyncio

ADMIN = {"user_id": "a03san_admin", "role": "admin", "email": "admin@rb.com"}


class _Req:
    def __init__(self, body=None):
        self._body = body or {}
        self.headers = {"content-type": "application/json"}

    async def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _bypass_staff(monkeypatch):
    async def _rs(_request):
        return dict(ADMIN)

    async def _noop(_x):
        return None

    async def _totp(_user, _code, action_label=""):
        return None

    monkeypatch.setattr(bl, "require_staff", _rs)
    monkeypatch.setattr(bl, "_assert_can_manage_blocklist", _noop)
    monkeypatch.setattr(bl, "_enforce_totp_step_up", _totp)
    yield


async def test_reimport_of_already_blocked_phone_sanitizes_active_empresa():
    tag = uuid.uuid4().int
    phone = normalize_phone(f"+535571{tag % 90000 + 10000}")
    emp = f"a03san_emp_{uuid.uuid4().hex[:8]}"
    await db.users.delete_many({"user_id": emp})
    await db.blocked_contacts.delete_many({"phone": phone})
    # Estado histórico: el teléfono YA está bloqueado, pero la Empresa quedó
    # ACTIVA (el código anterior no cubría su rol en ese momento).
    await db.blocked_contacts.insert_one({
        "id": uuid.uuid4().hex, "phone": phone, "email": None,
        "name": "Bloqueo previo", "reason": "import anterior",
        "created_at": iso(now_utc()), "created_by": ADMIN["user_id"],
        "source": "bulk_import"})
    await db.users.insert_one({
        "user_id": emp, "role": "empresa", "email": f"{emp}@rb.com",
        "phone": phone, "account_status": "active", "phone_verified": True})
    text = f"Empresa Historica\n{phone}\n"
    try:
        res = await bl.bulk_import_blocked_contacts(bl.BulkImportPayload(text=text), _Req({}))
        # El teléfono se salta como duplicado (no se re-inserta en la lista)...
        assert phone in res["skipped_duplicates"]
        assert res["imported_count"] == 0
        # ...pero la cuenta activa SÍ se sanea.
        assert res["affected_active_accounts"] >= 1
        u = await db.users.find_one({"user_id": emp}, {"_id": 0})
        assert u["account_status"] == "under_review"
        assert u["phone_verified"] is False
        assert u.get("under_review_since")
    finally:
        await db.users.delete_many({"user_id": emp})
        await db.blocked_contacts.delete_many({"phone": phone})
        await db.audit_logs.delete_many({"action": "blocked_contact.bulk_import"})


async def test_reimport_does_not_downgrade_already_blocked_account():
    """Control: una cuenta ya `blocked` NO debe degradarse a `under_review`, y
    una ya en `under_review` debe conservar su `under_review_since`."""
    tag = uuid.uuid4().int
    phone_b = normalize_phone(f"+535572{tag % 90000 + 10000}")
    phone_r = normalize_phone(f"+535573{tag % 90000 + 10000}")
    blocked_acc = f"a03san_blk_{uuid.uuid4().hex[:8]}"
    review_acc = f"a03san_rev_{uuid.uuid4().hex[:8]}"
    old_since = "2020-01-01T00:00:00+00:00"
    await db.users.delete_many({"user_id": {"$in": [blocked_acc, review_acc]}})
    await db.blocked_contacts.delete_many({"phone": {"$in": [phone_b, phone_r]}})
    for ph in (phone_b, phone_r):
        await db.blocked_contacts.insert_one({
            "id": uuid.uuid4().hex, "phone": ph, "email": None, "name": "prev",
            "reason": "x", "created_at": iso(now_utc()),
            "created_by": ADMIN["user_id"], "source": "bulk_import"})
    await db.users.insert_many([
        {"user_id": blocked_acc, "role": "empresa", "email": f"{blocked_acc}@rb.com",
         "phone": phone_b, "account_status": "blocked", "phone_verified": False},
        {"user_id": review_acc, "role": "normal", "email": f"{review_acc}@rb.com",
         "phone": phone_r, "account_status": "under_review", "phone_verified": False,
         "under_review_since": old_since},
    ])
    text = f"Bloqueado\n{phone_b}\n\nEnRevision\n{phone_r}\n"
    try:
        await bl.bulk_import_blocked_contacts(bl.BulkImportPayload(text=text), _Req({}))
        blk = await db.users.find_one({"user_id": blocked_acc}, {"_id": 0})
        rev = await db.users.find_one({"user_id": review_acc}, {"_id": 0})
        assert blk["account_status"] == "blocked"  # no degradada
        assert rev["account_status"] == "under_review"
        assert rev["under_review_since"] == old_since  # ticket preservado
    finally:
        await db.users.delete_many({"user_id": {"$in": [blocked_acc, review_acc]}})
        await db.blocked_contacts.delete_many({"phone": {"$in": [phone_b, phone_r]}})
        await db.audit_logs.delete_many({"action": "blocked_contact.bulk_import"})
