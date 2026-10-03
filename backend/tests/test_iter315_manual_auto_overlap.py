"""iter315 — CB10 v3 (CRÍTICA): la confirmación MANUAL y la automática podían
acreditar el MISMO pago. El candado de identidad económica (iter314) solo se
usaba en la ruta automática; `confirm_match` no reservaba esa identidad, así que
una decisión AUTOMÁTICA calculada antes (y pausada antes de insertar su reserva)
podía continuar tras una confirmación manual del mismo pago reimportado y generar
el segundo crédito.

Reproductor del informe: `cb_manual_auto_overlap()`.

Fix (iter315): `confirm_match` participa en el PROTOCOLO de reserva compartido —
reserva la identidad económica ANTES de acreditar. Quien no gana la reserva
pierde: la ruta manual se bloquea (409) y la automática cae a revisión. Un
operador puede resolver dos pagos REALES con atributos idénticos solo con
`override_duplicate` EXPLÍCITO y TRAZABLE.

Se prueban AMBOS órdenes de ejecución: manual-primero y automática-primero.
Infra basada en iter307 (confirm_match in-process con `require_permission`
stubbeado y `_run` que reinicia el loop de Motor).
"""
import asyncio
import os
import types
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

UID = "user_test_cli315"
MARK = "iter315"
ADMIN_ACTOR = {"user_id": "user_test_admin01", "role": "admin",
               "email": "admin.test@resilience.com", "name": "Admin Test"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code="USDT", uid=UID):
    u = _db().users.find_one({"user_id": uid}, {"_id": 0, "vip_balances": 1})
    return float(((u or {}).get("vip_balances") or {}).get(code) or 0.0)


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        _motor_client._io_loop = None
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


async def _stub_permission(*_a, **_k):
    return dict(ADMIN_ACTOR)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def setup_module():
    _db().users.update_one(
        {"user_id": UID},
        {"$set": {"user_id": UID, "email": f"{UID}@test.com", "name": UID,
                  "role": "vip", "vip_balances": {}, "applied_credit_ops": []}},
        upsert=True)


def teardown_module():
    _db().users.delete_many({"user_id": UID})
    _cleanup()


def _cleanup():
    db = _db()
    db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
    db.economic_credit_claims.delete_many({"tx_id": {"$regex": f"^tx_{MARK}"}})


def _mk_order(suffix, amount=100.0):
    oid = f"ord_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().orders.insert_one({
        "id": oid, "user_id": UID, "user_name": UID, "user_role": "vip",
        "status": "pending", "from_code": "USD", "to_code": "USDT",
        "amount_from": float(amount), "amount": float(amount),
        "amount_to": float(amount), "rate_applied": 1.0,
        "delivery_method": "accumulate", "holder_name": "Persona Prueba",
        "sender_name": "Persona Prueba",
        "created_at": _now(), "updated_at": _now()})
    return oid


def _mk_tx(suffix, amount=100.0):
    """Movimiento bancario con identidad económica estable (mismo remitente,
    importe, cuenta, fecha) pero huella DISTINTA — como PDF vs Excel."""
    tid = f"tx_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().bank_transactions.insert_one({
        "id": tid, "status": "unmatched", "direction": "credit",
        "amount": float(amount), "currency": "USD", "candidates": [],
        "bank_account_id": None, "sender_name": "Persona Prueba",
        "description": "Transferencia Persona Prueba",
        "transaction_date": _today(),
        "fingerprint": f"fp_{uuid.uuid4().hex}",
        "fingerprint_original": f"fpo_{suffix}_{uuid.uuid4().hex[:8]}",
        "created_at": _now(), "updated_at": _now()})
    return tid


async def _confirm(recon, tx_id, order_id, req, override=False):
    from fastapi import HTTPException
    try:
        await recon.confirm_match(
            tx_id, types.SimpleNamespace(order_id=order_id,
                                         override_duplicate=override), req)
        return 200
    except HTTPException as ex:
        return ex.status_code


class TestManualAutoOverlap:
    def setup_method(self, _):
        _cleanup()
        _db().users.update_one({"user_id": UID},
                               {"$set": {"vip_balances": {}}})

    def teardown_method(self, _):
        _cleanup()

    def test_manual_confirm_during_auto_pause_credits_once(self):
        """Orden #1 (automática empieza, manual gana durante su pausa). Solo
        existe la orden B; el motor elige B para la representación XLS, reserva
        su movimiento y se pausa ANTES de insertar su reserva económica. Llega
        la orden A + la representación PDF del mismo pago; la ruta MANUAL
        confirma A, reserva la identidad y acredita 100. La automática reanuda:
        su reserva económica FALLA (la tomó la manual) → cae a REVISIÓN. Un
        único crédito de 100; B queda pendiente."""
        order_b = _mk_order("B")
        tx_xls = _mk_tx("XLS")
        req = types.SimpleNamespace(client=None)

        async def flow():
            import routes.reconciliation as recon
            import services.reconciliation_matcher as rm
            real_claim = rm.claim_economic_identity
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            reached, gate = asyncio.Event(), asyncio.Event()

            async def gated_claim(key, tx_id):
                if tx_id == tx_xls:  # pausa SOLO la reserva de la automática
                    reached.set()
                    await asyncio.wait_for(gate.wait(), timeout=20)
                return await real_claim(key, tx_id)

            rm.claim_economic_identity = gated_claim
            try:
                tx_doc = await rm.db.bank_transactions.find_one(
                    {"id": tx_xls}, {"_id": 0})
                task_auto = asyncio.create_task(rm.run_matching(
                    {"currency": "USD", "bank_account_id": None}, [tx_doc]))
                await asyncio.wait_for(reached.wait(), 20)
                # Durante la pausa: aparece la orden A + PDF; confirmación manual.
                order_a = _mk_order("A")
                tx_pdf = _mk_tx("PDF")
                code_manual = await _confirm(recon, tx_pdf, order_a, req)
                gate.set()
                counts = await task_auto
                return order_a, tx_pdf, code_manual, counts
            finally:
                rm.claim_economic_identity = real_claim
                recon.require_permission = orig_perm

        order_a, tx_pdf, code_manual, counts = _run(flow)
        db = _db()
        assert code_manual == 200, f"la manual acredita A: {code_manual}"
        assert counts.get("review") == 1 and counts.get("auto", 0) == 0, counts
        assert db.orders.find_one({"id": order_a})["status"] == "approved"
        assert db.orders.find_one({"id": order_b})["status"] == "pending", \
            "B jamás se aprueba automáticamente: un pago no acredita dos órdenes"
        assert db.bank_transactions.find_one(
            {"id": tx_xls})["status"] == "manual_review"
        assert _bal("USDT") == 100.0, f"crédito único, no {_bal('USDT')}"

    def test_auto_first_blocks_manual_without_override(self):
        """Orden #2 (automática primero). El motor acredita B con la XLS y
        reserva la identidad. Luego la ruta MANUAL intenta confirmar A con la
        PDF del mismo pago: su reserva económica FALLA → 409, A sigue pendiente.
        Con `override_duplicate` EXPLÍCITO sí procede (dos pagos reales con
        atributos idénticos) y queda TRAZADO. Verifica ambos órdenes."""
        order_b = _mk_order("B")
        tx_xls = _mk_tx("XLS")
        req = types.SimpleNamespace(client=None)

        async def auto():
            import services.reconciliation_matcher as rm
            tx_doc = await rm.db.bank_transactions.find_one(
                {"id": tx_xls}, {"_id": 0})
            return await rm.run_matching(
                {"currency": "USD", "bank_account_id": None}, [tx_doc])
        counts = _run(auto)
        db = _db()
        assert counts.get("auto") == 1, counts
        assert db.orders.find_one({"id": order_b})["status"] == "approved"
        assert _bal("USDT") == 100.0

        order_a = _mk_order("A")
        tx_pdf = _mk_tx("PDF")

        async def manual_blocked():
            import routes.reconciliation as recon
            orig = recon.require_permission
            recon.require_permission = _stub_permission
            try:
                return await _confirm(recon, tx_pdf, order_a, req)
            finally:
                recon.require_permission = orig
        code = _run(manual_blocked)
        assert code == 409, f"la manual del mismo pago se bloquea: {code}"
        assert db.orders.find_one({"id": order_a})["status"] == "pending"
        assert _bal("USDT") == 100.0, "sin override no hay segundo crédito"

        async def manual_override():
            import routes.reconciliation as recon
            orig = recon.require_permission
            recon.require_permission = _stub_permission
            try:
                return await _confirm(recon, tx_pdf, order_a, req, override=True)
            finally:
                recon.require_permission = orig
        code_ov = _run(manual_override)
        assert code_ov == 200, f"el override explícito procede: {code_ov}"
        assert db.orders.find_one({"id": order_a})["status"] == "approved"
        txd = db.bank_transactions.find_one({"id": tx_pdf}, {"_id": 0})
        assert txd.get("duplicate_override_by") == ADMIN_ACTOR["user_id"], \
            "el override queda TRAZADO en el movimiento"
        assert _bal("USDT") == 200.0, "dos pagos reales, dos créditos (explícito)"
