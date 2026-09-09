"""iter261 — Correcciones de la auditoría de continuación F01–F06.

F01 burn_or_undo_*: la quema es un estado TERMINAL del log duradero —
    repetir la recuperación jamás convierte un bloqueo en una compensación
F02 amortización: el presupuesto por orden se reclama ATÓMICAMENTE en el
    plan (repayment_plans.consumed) — dos ejecutores nunca exceden el límite
F03 un fallo POSTERIOR al abono no libera el respaldo bancario del ítem
F04 el rollback de una orden acumulada distingue ciclos (accum_cycle)
F05 la aprobación de un ítem valida decision_cycle — peticiones obsoletas
    del ciclo anterior reciben 409
F06 Makefile test-critical incluye iter260 + iter261 (verificado por test)
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
UID = "user_test_vip01"
MARK = "iter261"
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
        db.users.delete_many({"user_id": {"$regex": f"^u_{MARK}"}})
        db.capital_requests.delete_many({"id": {"$regex": f"^cr_{MARK}"}})
        db.vip_batch_items.delete_many({"id": {"$regex": f"^vitem_{MARK}"}})
        db.vip_batches.delete_many({"id": {"$regex": f"^vb_{MARK}"}})
        db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
        db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
        db.redemptions.delete_many({"id": {"$regex": f"^red_{MARK}"}})
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


# ======================================================================
# F01 — la quema es terminal: repetir el aborto no crea saldo ni stock
# ======================================================================
class TestF01BurnIsTerminal(_Sandbox):
    def test_repeated_burn_without_effect_never_compensates(self):
        self._set_usdt(100)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().products.insert_one({"id": pid, "name": "F01", "stock": 5,
                                   "is_active": True, "created_at": OLD_TS})
        d_op = f"reactivate-debit:{MARK}:{uuid.uuid4().hex[:6]}"
        s_op = f"reactivate-stock:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from services.balances import burn_or_undo_debit
            from services.inventory import burn_or_undo_stock
            results = []
            for _ in range(3):  # el recuperador reintenta varias veces
                results.append(await burn_or_undo_debit(UID, "USDT", 100.0, d_op))
                results.append(await burn_or_undo_stock(pid, 1, s_op))
            return results

        results = _run(flow)
        assert all(r == "burned" for r in results), results
        assert _bal("USDT") == 100.0, \
            f"repetir la quema no puede crear saldo: {_bal('USDT')}"
        prod = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert prod["stock"] == 5, \
            f"repetir la quema no puede crear stock: {prod['stock']}"

    def test_real_effect_is_compensated_exactly_once(self):
        self._set_usdt(100)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().products.insert_one({"id": pid, "name": "F01b", "stock": 5,
                                   "is_active": True, "created_at": OLD_TS})
        d_op = f"reactivate-debit:{MARK}:{uuid.uuid4().hex[:6]}"
        s_op = f"reactivate-stock:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from services.balances import (debit_balance_idempotent,
                                           burn_or_undo_debit)
            from services.inventory import (apply_stock_idempotent,
                                            burn_or_undo_stock)
            assert await debit_balance_idempotent(UID, "USDT", 100.0, d_op) == "applied"
            assert await apply_stock_idempotent(pid, -1, s_op) == "applied"
            results = []
            for _ in range(3):
                results.append(await burn_or_undo_debit(UID, "USDT", 100.0, d_op))
                results.append(await burn_or_undo_stock(pid, 1, s_op))
            return results

        results = _run(flow)
        assert all(r == "undone" for r in results), results
        assert _bal("USDT") == 100.0, \
            f"la compensación debe aplicarse UNA sola vez: {_bal('USDT')}"
        prod = _db().products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert prod["stock"] == 5

    def test_healer_replay_after_cleanup_failure(self):
        """El escenario F01 del auditor: el healer aborta (quema ambos ops),
        el unset del plan falla, y el healer vuelve a pasar con el MISMO plan
        — no puede compensar lo que solo estaba quemado."""
        db = _db()
        self._set_usdt(100)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        rid = f"red_{MARK}_{uuid.uuid4().hex[:8]}"
        d_op = f"reactivate-debit:{rid}:{MARK}"
        s_op = f"reactivate-stock:{rid}:{MARK}"
        plan = {"stock_op": s_op, "debit_op": d_op, "amount": 100.0,
                "currency": "USDT", "quantity": 1, "target": "approved",
                "at": OLD_TS}
        db.products.insert_one({"id": pid, "name": "F01c", "stock": 5,
                                "is_active": True, "created_at": OLD_TS})
        db.redemptions.insert_one({
            "id": rid, "user_id": UID, "product_id": pid,
            "product_name": "F01c", "quantity": 1, "total_usd": 100.0,
            "settlement_currency": "USDT", "status": "rejected",
            "rejection_applied": True, "rejection_effects_done": True,
            "reactivation_pending": dict(plan), "created_at": OLD_TS})

        async def flow():
            from services.credit_recovery import heal_initializing_ops
            await heal_initializing_ops()  # pasada 1: quema y limpia el plan
            # simular que el unset del plan FALLÓ: reinsertar el plan tal cual
            # quedó tras el claim de aborto y repetir el healer.
            from db_client import db as adb
            await adb.redemptions.update_one(
                {"id": rid},
                {"$set": {"reactivation_pending": {**plan,
                                                   "state": "aborting"}}})
            await heal_initializing_ops()  # pasada 2: NO debe compensar nada
            await heal_initializing_ops()  # pasada 3: idem

        _run(flow)
        assert _bal("USDT") == 100.0, \
            f"repetir el healer no puede crear saldo (F01): {_bal('USDT')}"
        prod = db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
        assert prod["stock"] == 5, \
            f"repetir el healer no puede crear stock (F01): {prod['stock']}"
        doc = db.redemptions.find_one({"id": rid}, {"_id": 0})
        assert "reactivation_pending" not in doc

    def test_burned_op_blocks_late_debit_and_stock(self):
        self._set_usdt(100)
        pid = f"prod_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().products.insert_one({"id": pid, "name": "F01d", "stock": 5,
                                   "is_active": True, "created_at": OLD_TS})
        d_op = f"reactivate-debit:{MARK}:{uuid.uuid4().hex[:6]}"
        s_op = f"reactivate-stock:{MARK}:{uuid.uuid4().hex[:6]}"

        async def flow():
            from services.balances import (burn_or_undo_debit,
                                           debit_balance_idempotent)
            from services.inventory import (burn_or_undo_stock,
                                            apply_stock_idempotent)
            await burn_or_undo_debit(UID, "USDT", 100.0, d_op)
            await burn_or_undo_stock(pid, 1, s_op)
            late_d = await debit_balance_idempotent(UID, "USDT", 100.0, d_op)
            late_s = await apply_stock_idempotent(pid, -1, s_op)
            return late_d, late_s

        late_d, late_s = _run(flow)
        assert late_d == "duplicate" and late_s == "duplicate", (late_d, late_s)
        assert _bal("USDT") == 100.0
        assert _db().products.find_one({"id": pid})["stock"] == 5


# ======================================================================
# F02 — el presupuesto de amortización es un límite atómico global
# ======================================================================
class _PausingCapitalColl:
    """Proxy: la PRIMERA consulta de contribuciones previas pausa su to_list
    (reproduce al ejecutor A leyendo prior=0 antes de que B termine)."""

    def __init__(self, real, order_id, started, go):
        self._real, self._oid = real, order_id
        self._started, self._go = started, go
        self._pending = True

    def find(self, q, *a, **k):
        cursor = self._real.find(q, *a, **k)
        if self._pending and isinstance(q, dict) \
                and q.get("repayment_events.order_id") == self._oid:
            self._pending = False
            outer = self

            class PausingCursor:
                def sort(self, *sa, **sk):
                    cursor.sort(*sa, **sk)
                    return self

                async def to_list(self, n):
                    rows = await cursor.to_list(n)
                    outer._started.set()
                    await outer._go.wait()
                    return rows

            return PausingCursor()
        return cursor

    def __getattr__(self, name):
        return getattr(self._real, name)


class _DBProxy:
    def __init__(self, real, coll_name, coll):
        self._real, self._name, self._coll = real, coll_name, coll

    def __getattr__(self, name):
        if name == self._name:
            return self._coll
        return getattr(self._real, name)

    def __getitem__(self, name):
        return self.__getattr__(name)


class TestF02BudgetAtomicity(_Sandbox):
    def test_prior_read_before_debt_paid_off_cannot_exceed_budget(self):
        db = _db()
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        cra = f"cr_{MARK}_a_{uuid.uuid4().hex[:6]}"
        crb = f"cr_{MARK}_b_{uuid.uuid4().hex[:6]}"
        db.capital_requests.insert_one({
            "id": cra, "user_id": UID, "currency_code": "USDT",
            "status": "disbursed", "debt_remaining": 10.0,
            "discount_pct": 10.0, "disbursed_at": "1", "created_at": OLD_TS})
        db.capital_requests.insert_one({
            "id": crb, "user_id": UID, "currency_code": "USDT",
            "status": "disbursed", "debt_remaining": 100.0,
            "discount_pct": 50.0, "disbursed_at": "2", "created_at": OLD_TS})

        async def flow():
            import services.balances as bal
            from db_client import db as adb
            started, go = asyncio.Event(), asyncio.Event()
            real_db = bal.db
            bal.db = _DBProxy(real_db, "capital_requests",
                              _PausingCapitalColl(adb.capital_requests, oid,
                                                  started, go))
            try:
                # A: lee prior=0 y se pausa ANTES de leer las deudas activas
                task_a = asyncio.create_task(
                    bal._apply_capital_request_repayment(UID, "USDT", 100.0, oid))
                await asyncio.wait_for(started.wait(), timeout=10)
                bal.db = real_db  # B corre con la BD real, sin pausas
                net_b = await bal._apply_capital_request_repayment(
                    UID, "USDT", 100.0, oid)
                go.set()
                net_a = await task_a
                return net_a, net_b
            finally:
                bal.db = real_db

        net_a, net_b = _run(flow)
        docs = list(_db().capital_requests.find(
            {"id": {"$in": [cra, crb]}}, {"_id": 0}))
        paid = sum(float(ev.get("amount") or 0) for d in docs
                   for ev in (d.get("repayment_events") or []))
        assert paid == 10.0, \
            f"presupuesto 10 → amortización total 10, no {paid} (F02)"
        assert net_a == 90.0 and net_b == 90.0, (net_a, net_b)
        b = next(d for d in docs if d["id"] == crb)
        assert float(b["debt_remaining"]) == 100.0, \
            "la deuda B no puede recibir presupuesto ya consumido en A"


# ======================================================================
# F03 — un fallo tras el abono NO libera el movimiento bancario
# ======================================================================
class TestF03PostCreditFailureKeepsBankClaim(_Sandbox):
    def _mk_item(self):
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().vip_batch_items.insert_one({
            "id": iid, "batch_id": f"vb_{MARK}_x", "vip_user_id": UID,
            "status": "pending", "from_code": "USD", "to_code": "USDT",
            "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
            "holder_name": "Persona Prueba", "created_at": OLD_TS})
        return iid

    def test_failure_after_credit_keeps_transaction_reserved(self):
        db = _db()
        self._set_usdt(0)
        i1, i2 = self._mk_item(), self._mk_item()
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        db.bank_transactions.insert_one({
            "id": tx, "status": "manual_review", "direction": "credit",
            "amount": 100.0, "currency": "USD", "candidates": [],
            "transaction_date": "2026-01-01", "created_at": OLD_TS,
            "updated_at": OLD_TS})

        async def flow():
            import types
            import services.credit_markers as cm
            import routes.reconciliation as recon
            from fastapi import HTTPException
            real_apply = cm.apply_and_clear
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission

            async def failing_apply(coll, doc_id, marker, key_field="id"):
                # acredita de verdad y falla ANTES de limpiar el marker —
                # el fallo post-abono del auditor (F03).
                from services.balances import credit_balance_idempotent
                await credit_balance_idempotent(
                    marker["user_id"], marker["code"],
                    float(marker["amount"]), marker["op_id"],
                    legacy_usd=bool(marker.get("legacy_usd")))
                raise RuntimeError("simulated post-credit failure")

            cm.apply_and_clear = failing_apply
            req = types.SimpleNamespace(client=None)
            try:
                first = await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=i1), req)
            finally:
                cm.apply_and_clear = real_apply
            # segundo intento con OTRO ítem: el movimiento debe seguir
            # reservado/enlazado al primero.
            second = None
            try:
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=i2), req)
                second = "approved"
            except HTTPException as ex:
                second = ex.status_code
            finally:
                recon.require_permission = orig_perm
            # el healer completa la limpieza pendiente sin duplicar el abono
            # (envejecer el marker: el healer solo toca los añejos >120s)
            from db_client import db as adb
            await adb.vip_batch_items.update_one(
                {"id": i1}, {"$set": {"credit_pending.at": OLD_TS}})
            from services.credit_recovery import heal_pending_credits
            await heal_pending_credits()
            return first, second

        first, second = _run(flow)
        assert first is not None, "el primer confirm debe completarse"
        assert second == 409, \
            f"el movimiento no puede respaldar un segundo ítem (F03): {second}"
        assert _bal("USDT") == 100.0, \
            f"un cobro de 100 → 100 acreditados, no {_bal('USDT')} (F03)"
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == i1
        d1 = _db().vip_batch_items.find_one({"id": i1}, {"_id": 0})
        assert d1["status"] == "approved"
        assert "credit_pending" not in d1, "el healer limpia el marker"
        d2 = _db().vip_batch_items.find_one({"id": i2}, {"_id": 0})
        assert d2["status"] == "pending"


# ======================================================================
# F04 — el rollback de una orden acumulada distingue ciclos
# ======================================================================
class TestF04AccumulatedRollbackCycles(_Sandbox):
    def test_three_full_cycles_each_rollback_debits(self):
        db = _db()
        self._set_usdt(0)
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        db.orders.insert_one({
            "id": oid, "user_id": UID, "status": "pending",
            "delivery_method": "accumulate", "user_role": "vip",
            "amount_from": 100.0, "from_code": "USD",
            "amount_to": 100.0, "to_code": "USDT",
            "created_at": OLD_TS, "updated_at": OLD_TS})
        db.bank_transactions.insert_one({
            "id": tx, "status": "unmatched", "direction": "credit",
            "amount": 100.0, "currency": "USD", "candidates": [],
            "created_at": OLD_TS, "updated_at": OLD_TS})

        for cycle in range(3):
            # aprobar + acumular (simulado: abono real de un ciclo nuevo)
            db.orders.update_one({"id": oid}, {"$set": {
                "status": "approved", "accumulated_at": now,
                "reconciliation": {"bank_transaction_id": tx,
                                   "matched_at": now}}})
            db.bank_transactions.update_one({"id": tx}, {"$set": {
                "status": "manual_matched", "matched_order_id": oid,
                "matched_kind": "order"}})
            db.users.update_one({"user_id": UID},
                                {"$inc": {"vip_balances.USDT": 100.0}})
            assert _bal("USDT") == 100.0, f"ciclo {cycle}: abono previo"
            r = requests.post(
                f"{API}/admin/reconciliation/transactions/{tx}/rollback",
                headers=ADM_H, json={"reason": f"prueba F04 ciclo {cycle}"},
                timeout=20)
            assert r.status_code == 200, f"ciclo {cycle}: {r.text}"
            assert _bal("USDT") == 0.0, \
                (f"ciclo {cycle}: cada rollback debe devolver el saldo a 0 "
                 f"(F04), quedó {_bal('USDT')}")
            order = db.orders.find_one({"id": oid}, {"_id": 0})
            assert order["status"] == "pending"
            assert int(order.get("accum_cycle") or 0) == cycle + 1
            assert db.bank_transactions.find_one(
                {"id": tx})["status"] == "unmatched"


# ======================================================================
# F05 — una aprobación obsoleta no cruza el ciclo de decisión
# ======================================================================
class TestF05StaleApprovalCycle(_Sandbox):
    def test_stale_approval_rejected_after_rollback_cycle(self):
        db = _db()
        self._set_usdt(100)  # saldo tras el abono del ciclo 0 (se revierte)
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        tx = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        db.vip_batch_items.insert_one({
            "id": iid, "batch_id": f"vb_{MARK}_x", "vip_user_id": UID,
            "status": "pending", "from_code": "USD", "to_code": "USDT",
            "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
            "holder_name": "Persona Prueba", "created_at": OLD_TS})
        self._set_usdt(0)

        async def flow():
            import services.vip_batch_ops as vbo
            from fastapi import HTTPException
            from services.reconciliation_matcher import (
                rollback_batch_item_from_reconciliation as rb)
            real_rates = vbo.build_rate_lookup
            started, go = asyncio.Event(), asyncio.Event()

            async def paused(*a, **k):
                if not started.is_set():
                    started.set()
                    await go.wait()
                return await real_rates(*a, **k)

            vbo.build_rate_lookup = paused
            staff = dict(ADMIN_ACTOR)
            try:
                # petición VIEJA: lee el ítem en ciclo 0 y se pausa
                stale = asyncio.create_task(
                    vbo.apply_item_decision(iid, "approved", staff))
                await asyncio.wait_for(started.wait(), timeout=10)
                # mientras tanto: aprobar (ciclo 0) y revertir → ciclo 1
                await vbo.apply_item_decision(iid, "approved", staff)
                snap = dict(_db().vip_batch_items.find_one({"id": iid},
                                                           {"_id": 0}))
                snap["reconciliation"] = {"bank_transaction_id": tx}
                _db().vip_batch_items.update_one(
                    {"id": iid},
                    {"$set": {"reconciliation": {"bank_transaction_id": tx}}})
                await rb(snap, tx, staff, "prueba F05")
                go.set()
                try:
                    await stale
                    return "stale_won"
                except HTTPException as ex:
                    return ex.status_code
            finally:
                vbo.build_rate_lookup = real_rates

        stale_result = _run(flow)
        assert stale_result == 409, \
            f"la aprobación obsoleta debe recibir 409 (F05): {stale_result}"
        doc = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert doc["status"] == "pending", \
            "el ítem del ciclo nuevo sigue pendiente (sin aprobación fantasma)"
        assert int(doc.get("decision_cycle") or 0) == 1
        assert _bal("USDT") == 0.0, \
            f"abono 100 y reverso 100 → saldo 0, no {_bal('USDT')}"

        # la aprobación LEGÍTIMA del ciclo 1 acredita exactamente una vez
        async def approve_new_cycle():
            import services.vip_batch_ops as vbo
            await vbo.apply_item_decision(iid, "approved", dict(ADMIN_ACTOR))

        _run(approve_new_cycle)
        doc = db.vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert doc["status"] == "approved"
        assert _bal("USDT") == 100.0, \
            f"el ciclo nuevo abona con su propio op (100): {_bal('USDT')}"


# ======================================================================
# F06 — las regresiones de auditoría están en el conjunto de CI
# ======================================================================
class TestF06CICoverage:
    def test_makefile_critical_includes_audit_regressions(self):
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        for f in ("test_iter254_audit_fixes.py", "test_iter256_revision_fixes.py",
                  "test_iter257_deep_audit.py",
                  "test_iter260_continuation_audit.py",
                  "test_iter261_audit_f_fixes.py"):
            assert f in target, f"{f} debe estar en make test-critical (F06)"
