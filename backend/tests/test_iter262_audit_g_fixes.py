"""iter262 — Correcciones de la Auditoría 6 (G01–G04).

G01 burn_or_undo_*: el bloqueo usa un TOKEN propio (`op:burn`) — la presencia
    del op real SIEMPRE significa efecto real: un débito/reserva real se
    devuelve exactamente una vez y una quema jamás compensa
G02 amortización: las reservas de presupuesto son ASIGNACIONES RECUPERABLES
    (allocs reserved→applied|canceladas) — el neto acreditado + la deuda
    realmente amortizada siempre suman el importe de la orden
G03 rollback: el claim exige el CICLO leído — una reversión obsoleta recibe
    409 y no puede reclamar un ciclo re-acreditado (órdenes e ítems de lote)
G04 conciliación: un sello preparado SIN aprobación no activa la reanudación —
    el reintento re-ejecuta la aprobación idempotente y abona una sola vez
"""
import asyncio
import os
import types
import uuid

from pymongo import MongoClient

from conftest import ADMIN_TOKEN  # noqa: F401 — fuerza el conftest compartido

UID = "user_test_vip01"
MARK = "iter262"
OLD_TS = "2026-01-01T00:00:00+00:00"

ADMIN_ACTOR = {"user_id": "user_test_admin01", "role": "admin",
               "email": "admin.test@resilience.com", "name": "Admin Test"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bal(code, uid=UID):
    u = _db().users.find_one({"user_id": uid},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    amt = float(((u or {}).get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        amt += float((u or {}).get("vip_balance_usd") or 0.0)
    return amt


def _run(async_fn):
    # Motor cachea su event loop en el primer uso: re-vincular por corrida.
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


class _Sandbox:
    def setup_method(self, _):
        db = _db()
        self._orig = db.users.find_one(
            {"user_id": UID},
            {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1}) or {}

    def teardown_method(self, _):
        db = _db()
        db.capital_requests.delete_many({"id": {"$regex": f"^cr_{MARK}"}})
        db.vip_batch_items.delete_many({"id": {"$regex": f"^vitem_{MARK}"}})
        db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
        db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
        db.products.delete_many({"id": {"$regex": f"^prod_{MARK}"}})
        db.repayment_plans.delete_many({"order_id": {"$regex": f"^ord_{MARK}"}})
        db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
        db.stock_ops.delete_many({"op_id": {"$regex": MARK}})
        db.users.update_one({"user_id": UID}, {"$pull": {
            "applied_credit_ops": {"$regex": MARK}}})
        db.users.update_one({"user_id": UID}, {"$set": {
            "vip_balances": self._orig.get("vip_balances") or {},
            "vip_balance_usd": float(self._orig.get("vip_balance_usd") or 0.0)}})

    def _set_usdt(self, amount, uid=UID):
        _db().users.update_one({"user_id": uid},
                               {"$set": {"vip_balances.USDT": float(amount)}})

    def _mk_product(self, stock=5):
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().products.insert_one({"id": pid, "name": "G", "stock": stock,
                                   "is_active": True, "created_at": OLD_TS})
        return pid


# ======================================================================
# G01 — quema con token propio: efecto real ⇒ devolución exactamente una
# vez; bloqueo sin efecto ⇒ jamás compensa
# ======================================================================
class TestG01BurnTokenEvidence(_Sandbox):
    def test_burned_seal_over_real_debit_is_compensated(self):
        """Variante A del auditor: débito real con log 'pending' (falló
        mark_applied), aborto que selló 'burned' y murió antes de resolver.
        El reintento DEBE devolver los 100."""
        db = _db()
        self._set_usdt(100)
        d_op = f"g01a-debit:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from db_client import db as adb
            from services.balances import (debit_balance_idempotent,
                                           burn_or_undo_debit)
            assert await debit_balance_idempotent(UID, "USDT", 100.0, d_op) == "applied"
            # crash 1: la escritura que marcaba el log 'applied' nunca llegó
            await adb.credit_ops.update_one({"op_id": d_op},
                                            {"$set": {"state": "pending"}})
            # crash 2: el abortador selló la quema y murió antes de resolver
            await adb.credit_ops.update_one(
                {"op_id": d_op}, {"$set": {"state": "burned", "burned": True}})
            return [await burn_or_undo_debit(UID, "USDT", 100.0, d_op)
                    for _ in range(3)]

        results = _run(flow)
        assert all(r == "undone" for r in results), results
        assert _bal("USDT") == 100.0, \
            f"un débito real debe devolverse exactamente una vez: {_bal('USDT')}"
        log = db.credit_ops.find_one({"op_id": d_op}, {"_id": 0, "state": 1})
        assert log["state"] == "undone"

    def test_burned_seal_over_real_reserve_is_undone(self):
        """Variante A con stock: reserva real + sello 'burned' interrumpido —
        el reintento repone la unidad exactamente una vez."""
        db = _db()
        pid = self._mk_product(stock=5)
        s_op = f"g01a-stock:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from db_client import db as adb
            from services.inventory import (apply_stock_idempotent,
                                            burn_or_undo_stock)
            assert await apply_stock_idempotent(pid, -1, s_op) == "applied"
            await adb.stock_ops.update_one({"op_id": s_op},
                                           {"$set": {"state": "pending"}})
            await adb.stock_ops.update_one(
                {"op_id": s_op}, {"$set": {"state": "burned", "burned": True}})
            return [await burn_or_undo_stock(pid, 1, s_op) for _ in range(3)]

        results = _run(flow)
        assert all(r == "undone" for r in results), results
        prod = db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert prod["stock"] == 5, \
            f"la reserva real debe reponerse exactamente una vez: {prod['stock']}"

    def test_abort_of_unmarked_real_debit_compensates_once(self):
        """Fallo después del movimiento y ANTES de marcar el log: el aborto
        desde cero detecta el op real en el registro y compensa una vez."""
        self._set_usdt(100)
        d_op = f"g01c-debit:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from db_client import db as adb
            from services.balances import (debit_balance_idempotent,
                                           burn_or_undo_debit)
            assert await debit_balance_idempotent(UID, "USDT", 100.0, d_op) == "applied"
            await adb.credit_ops.update_one({"op_id": d_op},
                                            {"$set": {"state": "pending"}})
            return [await burn_or_undo_debit(UID, "USDT", 100.0, d_op)
                    for _ in range(3)]

        results = _run(flow)
        assert all(r == "undone" for r in results), results
        assert _bal("USDT") == 100.0, _bal("USDT")

    def test_interleaved_aborters_without_debit_never_credit(self):
        """Variante B del auditor: B selló la quema e insertó el token; A
        reanuda — el token NO puede confundirse con un débito real."""
        db = _db()
        self._set_usdt(100)
        d_op = f"g01b-debit:{MARK}:{uuid.uuid4().hex[:6]}"
        db.credit_ops.insert_one({
            "op_id": d_op, "state": "burned", "burned": True, "user_id": UID,
            "code": "USDT", "amount": 100.0, "kind": "debit", "at": OLD_TS})
        db.users.update_one({"user_id": UID},
                            {"$push": {"applied_credit_ops": f"{d_op}:burn"}})

        async def flow():
            from services.balances import (burn_or_undo_debit,
                                           debit_balance_idempotent)
            results = [await burn_or_undo_debit(UID, "USDT", 100.0, d_op)
                       for _ in range(3)]
            late = await debit_balance_idempotent(UID, "USDT", 100.0, d_op)
            return results, late

        results, late = _run(flow)
        assert all(r == "burned" for r in results), results
        assert late == "duplicate", late
        assert _bal("USDT") == 100.0, \
            f"dos abortos sin débito jamás crean saldo (G01b): {_bal('USDT')}"

    def test_two_concurrent_aborters_converge(self):
        """Dos recuperadores simultáneos sobre el mismo op sin débito previo:
        ambos convergen en 'burned' y el saldo/stock no cambia."""
        self._set_usdt(100)
        pid = self._mk_product(stock=5)
        d_op = f"g01d-debit:{MARK}:{uuid.uuid4().hex[:6]}"
        s_op = f"g01d-stock:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from services.balances import burn_or_undo_debit
            from services.inventory import burn_or_undo_stock
            r_bal = await asyncio.gather(
                burn_or_undo_debit(UID, "USDT", 100.0, d_op),
                burn_or_undo_debit(UID, "USDT", 100.0, d_op))
            r_stk = await asyncio.gather(
                burn_or_undo_stock(pid, 1, s_op),
                burn_or_undo_stock(pid, 1, s_op))
            return r_bal, r_stk

        r_bal, r_stk = _run(flow)
        assert list(r_bal) == ["burned", "burned"], r_bal
        assert list(r_stk) == ["burned", "burned"], r_stk
        assert _bal("USDT") == 100.0
        assert _db().products.find_one({"id": pid})["stock"] == 5

    def test_burn_token_blocks_late_debit_even_without_log(self):
        """El guard $nin del registro bloquea por sí solo: aunque el log
        duradero desaparezca, el token `op:burn` rechaza el débito tardío."""
        db = _db()
        self._set_usdt(100)
        pid = self._mk_product(stock=5)
        d_op = f"g01e-debit:{MARK}:{uuid.uuid4().hex[:6]}"
        s_op = f"g01e-stock:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from db_client import db as adb
            from services.balances import (burn_or_undo_debit,
                                           debit_balance_idempotent)
            from services.inventory import (burn_or_undo_stock,
                                            apply_stock_idempotent)
            assert await burn_or_undo_debit(UID, "USDT", 100.0, d_op) == "burned"
            assert await burn_or_undo_stock(pid, 1, s_op) == "burned"
            # simular pérdida del log duradero: solo queda el token
            await adb.credit_ops.delete_one({"op_id": d_op})
            await adb.stock_ops.delete_one({"op_id": s_op})
            late_d = await debit_balance_idempotent(UID, "USDT", 100.0, d_op)
            late_s = await apply_stock_idempotent(pid, -1, s_op)
            return late_d, late_s

        late_d, late_s = _run(flow)
        assert late_d == "duplicate" and late_s == "duplicate", (late_d, late_s)
        assert _bal("USDT") == 100.0
        assert db.products.find_one({"id": pid})["stock"] == 5


# ======================================================================
# G02 — reserva de presupuesto ≠ amortización real: abono + deuda
# amortizada SIEMPRE suman el importe de la orden
# ======================================================================
class TestG02RecoverableAllocations(_Sandbox):
    def test_orphan_reservation_completed_by_healer(self):
        """Escenario del auditor: la reserva de 10 queda huérfana (falló la
        escritura de la deuda) y el recuperador pasa — el re-drive completa
        la amortización: se acreditan 90 Y la deuda baja a 90."""
        db = _db()
        self._set_usdt(0)
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        cr = f"cr_{MARK}_{uuid.uuid4().hex[:6]}"
        db.capital_requests.insert_one({
            "id": cr, "user_id": UID, "currency_code": "USDT",
            "status": "disbursed", "debt_remaining": 100.0,
            "discount_pct": 10.0, "disbursed_at": "1", "created_at": OLD_TS})
        db.orders.insert_one({
            "id": oid, "user_id": UID, "status": "approved",
            "amount_from": 100.0, "from_code": "USD",
            "amount_to": 100.0, "to_code": "USDT",
            "created_at": OLD_TS, "updated_at": OLD_TS})

        async def flow():
            import services.balances as bal
            from db_client import db as adb
            real_apply = bal._apply_debt_contribution

            async def failing_apply(*_a, **_k):
                raise RuntimeError("simulated crash after budget reservation")

            bal._apply_debt_contribution = failing_apply
            crashed = False
            try:
                order = await adb.orders.find_one({"id": oid}, {"_id": 0})
                await bal.accumulate_vip_balance(order)
            except RuntimeError:
                crashed = True
            finally:
                bal._apply_debt_contribution = real_apply
            # estado intermedio: reserva sin deuda escrita, marker sin preparar
            plan = await adb.repayment_plans.find_one(
                {"order_id": oid, "currency": "USDT"}, {"_id": 0})
            debt = await adb.capital_requests.find_one({"id": cr}, {"_id": 0})
            mid = (crashed, float(plan.get("consumed") or 0),
                   (plan.get("allocs") or [{}])[0].get("state"),
                   float(debt.get("debt_remaining") or 0))
            # envejecer el marker y correr el recuperador real
            await adb.orders.update_one(
                {"id": oid}, {"$set": {"credit_pending.at": OLD_TS}})
            from services.credit_recovery import heal_pending_credits
            await heal_pending_credits()
            return mid

        crashed, consumed_mid, alloc_mid, debt_mid = _run(flow)
        assert crashed, "el crash simulado debe propagarse"
        assert consumed_mid == 10.0 and alloc_mid == "reserved", \
            (consumed_mid, alloc_mid)
        assert debt_mid == 100.0, "la deuda no se escribió antes del crash"

        assert _bal("USDT") == 90.0, \
            f"neto acreditado debe ser 90 (G02): {_bal('USDT')}"
        debt = db.capital_requests.find_one({"id": cr}, {"_id": 0})
        assert float(debt["debt_remaining"]) == 90.0, \
            f"la amortización de 10 debe ser REAL: {debt['debt_remaining']}"
        events = [ev for ev in (debt.get("repayment_events") or [])
                  if ev.get("order_id") == oid]
        assert len(events) == 1 and float(events[0]["amount"]) == 10.0, events
        assert _bal("USDT") + float(events[0]["amount"]) == 100.0, \
            "abono + amortización real deben sumar el importe de la orden"
        plan = db.repayment_plans.find_one({"order_id": oid, "currency": "USDT"},
                                           {"_id": 0})
        allocs = plan.get("allocs") or []
        assert len(allocs) == 1 and allocs[0]["state"] == "applied", allocs
        order = db.orders.find_one({"id": oid}, {"_id": 0})
        assert "credit_pending" not in order, "el marker se limpia al abonar"

    def test_unfillable_reservation_cancelled_and_rebudgeted(self):
        """Una reserva sobre una deuda ya cerrada se CANCELA (devuelve el
        presupuesto) y el presupuesto real se aplica a la deuda viva."""
        db = _db()
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        cra = f"cr_{MARK}_a_{uuid.uuid4().hex[:6]}"
        crb = f"cr_{MARK}_b_{uuid.uuid4().hex[:6]}"
        db.capital_requests.insert_one({
            "id": cra, "user_id": UID, "currency_code": "USDT",
            "status": "paid_off", "debt_remaining": 0.0,
            "discount_pct": 10.0, "disbursed_at": "1", "created_at": OLD_TS})
        db.capital_requests.insert_one({
            "id": crb, "user_id": UID, "currency_code": "USDT",
            "status": "disbursed", "debt_remaining": 100.0,
            "discount_pct": 10.0, "disbursed_at": "2", "created_at": OLD_TS})
        db.repayment_plans.insert_one({
            "order_id": oid, "currency": "USDT", "user_id": UID,
            "gross": 100.0, "pct": 10.0, "budget_total": 10.0,
            "consumed": 10.0,
            "allocs": [{"nonce": "orphan1", "debt_id": cra, "amount": 10.0,
                        "state": "reserved", "at": OLD_TS}],
            "at": OLD_TS})

        async def flow():
            from services.balances import _apply_capital_request_repayment
            return await _apply_capital_request_repayment(UID, "USDT", 100.0, oid)

        net = _run(flow)
        assert net == 90.0, f"neto 90 tras re-asignar el presupuesto: {net}"
        a = db.capital_requests.find_one({"id": cra}, {"_id": 0})
        assert not (a.get("repayment_events") or []), \
            "la deuda cerrada no puede recibir la reserva cancelada"
        b = db.capital_requests.find_one({"id": crb}, {"_id": 0})
        assert float(b["debt_remaining"]) == 90.0, b["debt_remaining"]
        plan = db.repayment_plans.find_one({"order_id": oid, "currency": "USDT"},
                                           {"_id": 0})
        assert float(plan["consumed"]) == 10.0, plan["consumed"]
        allocs = plan.get("allocs") or []
        assert [a_ for a_ in allocs if a_["nonce"] == "orphan1"] == [], \
            "la reserva huérfana debe cancelarse (pull)"
        assert len(allocs) == 1 and allocs[0]["state"] == "applied" \
            and allocs[0]["debt_id"] == crb, allocs


# ======================================================================
# G03 — una reversión obsoleta no puede reclamar el ciclo nuevo
# ======================================================================
class TestG03StaleRollbackCycle(_Sandbox):
    def test_stale_accum_rollback_gets_409_new_cycle_survives(self):
        db = _db()
        self._set_usdt(100)  # abono del ciclo 1 (re-acreditado tras rollback)
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        doc = {"id": oid, "user_id": UID, "status": "approved",
               "delivery_method": "accumulate", "accum_cycle": 1,
               "amount_from": 100.0, "from_code": "USD",
               "amount_to": 100.0, "to_code": "USDT",
               "accumulated_at": OLD_TS,
               "reconciliation": {"bank_transaction_id": tx},
               "created_at": OLD_TS, "updated_at": OLD_TS}
        db.orders.insert_one(dict(doc))
        stale = {**doc, "accum_cycle": 0}  # snapshot leído antes del rollback B

        async def flow():
            from fastapi import HTTPException
            from routes.reconciliation import _rollback_accumulated_order_credit
            try:
                await _rollback_accumulated_order_credit(stale, tx, "prueba G03")
                return "stale_won"
            except HTTPException as ex:
                return ex.status_code

        result = _run(flow)
        assert result == 409, \
            f"la reversión obsoleta debe recibir conflicto (G03): {result}"
        fresh = db.orders.find_one({"id": oid}, {"_id": 0})
        assert fresh["status"] == "approved", fresh["status"]
        assert int(fresh["accum_cycle"]) == 1
        assert "rollback_pending" not in fresh, \
            "la petición obsoleta no puede dejar un plan del ciclo viejo"
        assert _bal("USDT") == 100.0, \
            f"el abono del ciclo nuevo sigue intacto: {_bal('USDT')}"

        # la reversión LEGÍTIMA del ciclo 1 sí descuenta y avanza el ciclo
        async def legit():
            from routes.reconciliation import _rollback_accumulated_order_credit
            await _rollback_accumulated_order_credit(dict(doc), tx, "prueba G03")

        _run(legit)
        fresh = db.orders.find_one({"id": oid}, {"_id": 0})
        assert fresh["status"] == "pending"
        assert int(fresh["accum_cycle"]) == 2
        assert _bal("USDT") == 0.0, _bal("USDT")

    def test_stale_vitem_rollback_gets_409_new_cycle_survives(self):
        db = _db()
        self._set_usdt(100)
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        doc = {"id": iid, "batch_id": f"vb_{MARK}_x", "vip_user_id": UID,
               "status": "approved", "decision_cycle": 1,
               "from_code": "USD", "to_code": "USDT",
               "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
               "holder_name": "Persona Prueba",
               "reconciliation": {"bank_transaction_id": tx},
               "created_at": OLD_TS}
        db.vip_batch_items.insert_one(dict(doc))
        stale = {**doc, "decision_cycle": 0}

        async def flow():
            from fastapi import HTTPException
            from services.reconciliation_matcher import (
                rollback_batch_item_from_reconciliation as rb)
            try:
                await rb(stale, tx, dict(ADMIN_ACTOR), "prueba G03")
                return "stale_won"
            except HTTPException as ex:
                return ex.status_code

        result = _run(flow)
        assert result == 409, \
            f"la reversión obsoleta del ítem debe recibir 409 (G03): {result}"
        fresh = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert fresh["status"] == "approved"
        assert int(fresh["decision_cycle"]) == 1
        assert "rollback_pending" not in fresh
        assert _bal("USDT") == 100.0, _bal("USDT")

        async def legit():
            from services.reconciliation_matcher import (
                rollback_batch_item_from_reconciliation as rb)
            await rb(dict(doc), tx, dict(ADMIN_ACTOR), "prueba G03")

        _run(legit)
        fresh = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert fresh["status"] == "pending"
        assert int(fresh["decision_cycle"]) == 2
        assert _bal("USDT") == 0.0, _bal("USDT")


# ======================================================================
# G04 — un sello preparado sin aprobación NO activa la reanudación
# ======================================================================
class _Crash(BaseException):
    """Interrupción abrupta (no pasa por la limpieza de except Exception)."""


class TestG04ResumeRequiresPersistedDecision(_Sandbox):
    def _mk_item(self):
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().vip_batch_items.insert_one({
            "id": iid, "batch_id": f"vb_{MARK}_x", "vip_user_id": UID,
            "status": "pending", "from_code": "USD", "to_code": "USDT",
            "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
            "holder_name": "Persona Prueba", "created_at": OLD_TS})
        return iid

    def _mk_tx(self):
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().bank_transactions.insert_one({
            "id": tx, "status": "manual_review", "direction": "credit",
            "amount": 100.0, "currency": "USD", "candidates": [],
            "transaction_date": "2026-01-01", "created_at": OLD_TS,
            "updated_at": OLD_TS})
        return tx

    def test_interrupted_confirm_retry_completes_approval(self):
        """Escenario del auditor: crash abrupto entre el sello y la
        aprobación — el reintento DEBE aprobar y abonar exactamente una vez,
        nunca publicar la conciliación sin sus efectos."""
        db = _db()
        self._set_usdt(0)
        iid, tx = self._mk_item(), self._mk_tx()

        async def flow():
            import routes.reconciliation as recon
            import services.reconciliation_matcher as rm
            from fastapi import HTTPException
            orig_perm = recon.require_permission
            real_decide = rm.apply_item_decision
            recon.require_permission = _stub_permission

            async def abrupt(*_a, **_k):
                raise _Crash()

            req = types.SimpleNamespace(client=None)
            rm.apply_item_decision = abrupt
            crashed = False
            try:
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=iid), req)
            except _Crash:
                crashed = True
            finally:
                rm.apply_item_decision = real_decide
            from db_client import db as adb
            mid_item = await adb.vip_batch_items.find_one({"id": iid}, {"_id": 0})
            mid_tx = await adb.bank_transactions.find_one({"id": tx}, {"_id": 0})
            # reintento REAL de la misma conciliación
            try:
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=iid), req)
                # tercer intento: ya conciliado → conflicto, sin doble abono
                try:
                    await recon.confirm_match(
                        tx, types.SimpleNamespace(order_id=iid), req)
                    third = "approved_again"
                except HTTPException as ex:
                    third = ex.status_code
            finally:
                recon.require_permission = orig_perm
            return crashed, mid_item, mid_tx, third

        crashed, mid_item, mid_tx, third = _run(flow)
        assert crashed, "la interrupción abrupta debe propagarse"
        assert mid_item["status"] == "pending", \
            "estado intermedio del auditor: sello escrito, ítem aún pendiente"
        assert (mid_item.get("reconciliation") or {}) \
            .get("bank_transaction_id") == tx
        assert mid_tx["status"] == "manual_review", \
            "el crash ocurre antes de publicar la conciliación"
        assert third == 409, third

        item = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert item["status"] == "approved", \
            f"el reintento debe completar la aprobación (G04): {item['status']}"
        txd = db.bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == iid
        assert _bal("USDT") == 100.0, \
            f"un cobro de 100 → exactamente 100 acreditados: {_bal('USDT')}"

    def test_resume_after_persisted_decision_links_without_double_credit(self):
        """Contraparte E04 conservada: si la decisión SÍ quedó persistida
        (aprobado + sello) y solo faltó el enlace bancario, el reintento
        completa el enlace sin repetir la aprobación ni el abono."""
        db = _db()
        self._set_usdt(0)
        iid, tx = self._mk_item(), self._mk_tx()

        async def flow():
            import routes.reconciliation as recon
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            req = types.SimpleNamespace(client=None)
            try:
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=iid), req)
                # simular crash ANTES del update final del movimiento
                from db_client import db as adb
                await adb.bank_transactions.update_one(
                    {"id": tx},
                    {"$set": {"status": "manual_review",
                              "matching_claim": {"order_id": iid, "at": OLD_TS,
                                                 "by": ADMIN_ACTOR["user_id"]}},
                     "$unset": {"matched_order_id": "", "matched_kind": ""}})
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=iid), req)
            finally:
                recon.require_permission = orig_perm

        _run(flow)
        txd = db.bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == iid
        assert _bal("USDT") == 100.0, \
            f"la reanudación no puede duplicar el abono: {_bal('USDT')}"
        item = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert item["status"] == "approved"


# ======================================================================
# G — las regresiones de esta auditoría están en el conjunto de CI
# ======================================================================
class TestGCICoverage:
    def test_makefile_critical_includes_iter262(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter262_audit_g_fixes.py" in target, \
            "test_iter262 debe estar en make test-critical"
