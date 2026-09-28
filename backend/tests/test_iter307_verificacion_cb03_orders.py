"""iter307 — CB03 (crítica): doble acreditación al recuperar una reserva
vencida en la CONCILIACIÓN BANCARIA de ÓRDENES (informe 74a5f40, re-reportado
por el propietario).

Bug documentado: dos órdenes A y B compatibles con un ÚNICO abono de 100 USD;
A obtiene la reserva y se pausa antes de aprobar; la reserva supera 300 s; B
comprueba que A no tiene sello y decide recuperar la reserva vencida; A reanuda
y acredita 100 USDT; B reanuda, toma la reserva apoyándose en su comprobación
anterior y acredita OTROS 100 USDT → 200 USDT con un solo abono (tasa 1:1).

Fix (CB03 v4): el respaldo del abono se compromete de forma ATÓMICA y
EXCLUSIVA sobre el PROPIO movimiento (`credit_backing_order`, compare-and-set
ausente-o-este-destino) ANTES de acreditar. Si A ya comprometió el abono, la
recuperación de B no puede acreditar un segundo crédito; si B gana válidamente
la recuperación, A queda desplazada y no acredita. El total acreditado por el
abono es 100 USDT como máximo, y una única conciliación válida se completa (con
reintento) sin perder el respaldo del crédito. Una reserva vencida realmente
abandonada (sin crédito comprometido) sigue pudiendo recuperarse.
"""
import asyncio
import os
import types
import uuid
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

UID = "user_test_cli307"
MARK = "iter307"

ADMIN_ACTOR = {"user_id": "user_test_admin01", "role": "admin",
               "email": "admin.test@resilience.com", "name": "Admin Test"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code="USDT", uid=UID):
    u = _db().users.find_one({"user_id": uid},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    amt = float(((u or {}).get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        amt += float((u or {}).get("vip_balance_usd") or 0.0)
    return amt


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


def _old(seconds=400):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def setup_module():
    _db().users.update_one(
        {"user_id": UID},
        {"$set": {"user_id": UID, "email": f"{UID}@test.com", "name": UID,
                  "role": "vip", "vip_balances": {}, "applied_credit_ops": []}},
        upsert=True)


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": UID})
    _cleanup()


def _cleanup():
    db = _db()
    db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})


def _mk_order(oid_suffix, amount=100.0):
    oid = f"ord_{MARK}_{oid_suffix}_{uuid.uuid4().hex[:6]}"
    doc = {
        "id": oid, "user_id": UID, "user_name": UID, "user_role": "vip",
        "status": "pending", "from_code": "USD", "to_code": "USDT",
        "amount_from": float(amount), "amount": float(amount),
        "amount_to": float(amount), "rate_applied": 1.0,
        "delivery_method": "accumulate", "holder_name": "Persona Prueba",
        "created_at": _now(), "updated_at": _now(),
    }
    _db().orders.insert_one(dict(doc))
    return oid


def _mk_tx(matching_claim=None, status="manual_review"):
    tid = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
    doc = {"id": tid, "status": status, "direction": "credit",
           "amount": 100.0, "currency": "USD", "candidates": [],
           "sender_name": "Persona Prueba", "transaction_date": _now()[:10],
           "created_at": _now(), "updated_at": _now()}
    if matching_claim is not None:
        doc["matching_claim"] = matching_claim
    _db().bank_transactions.insert_one(dict(doc))
    return tid


def _set_bal(amount, code="USDT", uid=UID):
    _db().users.update_one({"user_id": uid},
                           {"$set": {f"vip_balances.{code}": float(amount)}})


async def _confirm(recon, tx_id, order_id, req):
    from fastapi import HTTPException
    try:
        await recon.confirm_match(
            tx_id, types.SimpleNamespace(order_id=order_id), req)
        return 200
    except HTTPException as ex:
        return ex.status_code


class TestCB03OrderRecovery:
    def setup_method(self, _):
        _cleanup()
        _set_bal(0)

    def teardown_method(self, _):
        _cleanup()

    def test_expired_recovery_after_credit_no_double_then_retry_closes(self):
        """Orden de ejecución #1 (A acredita antes de la recuperación de B).
        A reserva y se pausa antes de aprobar; su reserva vence (>300 s); B
        pasa sus comprobaciones (A sin sello, reserva vencida) y se pausa justo
        antes de comprometer el respaldo; A reanuda, acredita 100 USDT y su
        cierre pierde el token; B reanuda y su compromiso de respaldo se
        RECHAZA (ya es de A). Total = 100 USDT. El reintento de A completa el
        cierre sin volver a acreditar."""
        order_a = _mk_order("A")
        order_b = _mk_order("B")
        tx = _mk_tx()
        req = types.SimpleNamespace(client=None)

        async def flow():
            import routes.reconciliation as recon
            import services.reconciliation_matcher as rm
            real_approve = recon.approve_order_from_reconciliation
            real_backing = rm.claim_credit_backing
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            reached_a, gate_a = asyncio.Event(), asyncio.Event()
            reached_b, gate_b = asyncio.Event(), asyncio.Event()

            async def gated_approve(order, txd, actor, auto, match_uid=None):
                if order["id"] == order_a:
                    reached_a.set()
                    await asyncio.wait_for(gate_a.wait(), timeout=20)
                return await real_approve(order, txd, actor, auto,
                                          match_uid=match_uid)

            async def gated_backing(tx_id, target_id):
                if target_id == order_b:
                    reached_b.set()
                    await asyncio.wait_for(gate_b.wait(), timeout=20)
                return await real_backing(tx_id, target_id)

            recon.approve_order_from_reconciliation = gated_approve
            rm.claim_credit_backing = gated_backing
            try:
                task_a = asyncio.create_task(_confirm(recon, tx, order_a, req))
                await asyncio.wait_for(reached_a.wait(), 20)  # A reservó, pausa
                # la reserva de A vence (>300 s)
                _db().bank_transactions.update_one(
                    {"id": tx}, {"$set": {"matching_claim.at": _old()}})
                task_b = asyncio.create_task(_confirm(recon, tx, order_b, req))
                await asyncio.wait_for(reached_b.wait(), 20)  # B robó, pausa
                gate_a.set()
                code_a = await task_a       # A acredita; cierre pierde token
                gate_b.set()
                code_b = await task_b       # B: respaldo rechazado
                return code_a, code_b
            finally:
                recon.approve_order_from_reconciliation = real_approve
                rm.claim_credit_backing = real_backing
                recon.require_permission = orig_perm

        code_a, code_b = _run(flow)
        assert code_b == 409, f"la recuperación de B no puede acreditar: {code_b}"
        assert _bal("USDT") == 100.0, \
            f"un abono de 100 USD → máximo 100 USDT, no {_bal('USDT')} (CB03)"
        db = _db()
        oa = db.orders.find_one({"id": order_a}, {"_id": 0})
        ob = db.orders.find_one({"id": order_b}, {"_id": 0})
        assert oa["status"] == "approved" and oa.get("accumulated_at"), \
            "A acreditó una vez"
        assert ob["status"] == "pending", "B jamás acreditó"
        txd = db.bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd.get("credit_backing_order") == order_a, \
            "el respaldo del abono pertenece exclusivamente a A"
        # Reintento de A: completa el cierre sin volver a acreditar.
        async def retry():
            import routes.reconciliation as recon
            orig = recon.require_permission
            recon.require_permission = _stub_permission
            try:
                return await _confirm(recon, tx, order_a, req)
            finally:
                recon.require_permission = orig
        code_retry = _run(retry)
        assert code_retry == 200, f"el reintento de A debe cerrar: {code_retry}"
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == order_a
        assert _bal("USDT") == 100.0, "el cierre no vuelve a acreditar"

    def test_expired_recovery_before_credit_only_winner_credits(self):
        """Orden de ejecución #2 (B recupera y acredita ANTES de que A
        acredite). A reserva y se pausa antes de aprobar; su reserva vence; B
        recupera por completo (roba la reserva, aprueba, acredita y cierra);
        al reanudar, A queda DESPLAZADA y su compromiso de respaldo se rechaza
        — A no acredita. Total = 100 USDT (de B)."""
        order_a = _mk_order("A")
        order_b = _mk_order("B")
        tx = _mk_tx()
        req = types.SimpleNamespace(client=None)

        async def flow():
            import routes.reconciliation as recon
            real_approve = recon.approve_order_from_reconciliation
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            reached_a, gate_a = asyncio.Event(), asyncio.Event()

            async def gated_approve(order, txd, actor, auto, match_uid=None):
                if order["id"] == order_a:
                    reached_a.set()
                    await asyncio.wait_for(gate_a.wait(), timeout=20)
                return await real_approve(order, txd, actor, auto,
                                          match_uid=match_uid)

            recon.approve_order_from_reconciliation = gated_approve
            try:
                task_a = asyncio.create_task(_confirm(recon, tx, order_a, req))
                await asyncio.wait_for(reached_a.wait(), 20)
                _db().bank_transactions.update_one(
                    {"id": tx}, {"$set": {"matching_claim.at": _old()}})
                # B recupera y acredita por completo mientras A está pausada.
                code_b = await _confirm(recon, tx, order_b, req)
                gate_a.set()
                code_a = await task_a
                return code_a, code_b
            finally:
                recon.approve_order_from_reconciliation = real_approve
                recon.require_permission = orig_perm

        code_a, code_b = _run(flow)
        assert code_b == 200, f"B gana la recuperación válida: {code_b}"
        assert code_a == 409, f"A queda desplazada y no acredita: {code_a}"
        assert _bal("USDT") == 100.0, "solo B acreditó (100 USDT)"
        db = _db()
        assert db.orders.find_one({"id": order_a})["status"] == "pending"
        ob = db.orders.find_one({"id": order_b})
        assert ob["status"] == "approved" and ob.get("accumulated_at")
        txd = db.bank_transactions.find_one({"id": tx})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == order_b
        assert txd.get("credit_backing_order") == order_b

    def test_truly_abandoned_reservation_is_recoverable(self):
        """Una reserva vencida REALMENTE abandonada (reservada, jamás acreditó,
        sin sello ni respaldo) debe seguir pudiendo recuperarse: B concilia sin
        obstáculos y acredita una vez."""
        order_b = _mk_order("B")
        tx = _mk_tx(matching_claim={"order_id": f"ord_{MARK}_dead",
                                    "at": _old(), "by": "ghost",
                                    "token": "tok_dead"})
        req = types.SimpleNamespace(client=None)

        async def flow():
            import routes.reconciliation as recon
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            try:
                return await _confirm(recon, tx, order_b, req)
            finally:
                recon.require_permission = orig_perm

        code_b = _run(flow)
        assert code_b == 200, f"la reserva abandonada se recupera: {code_b}"
        assert _bal("USDT") == 100.0
        txd = _db().bank_transactions.find_one({"id": tx})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == order_b


class TestCICoverage:
    def test_makefile_critical_includes_iter307(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter307_verificacion_cb03_orders.py" in target
