"""iter302 — Verificación de conciliación (informe 523229f): cierre de las
3 variantes residuales CB03, CB05 y CB08.

CB03 (crítica) La PROPIEDAD del intento alcanza la decisión y el crédito del
     ítem VIP: el sello lleva el token del intento, una recuperación desplaza
     ATÓMICAMENTE al intento anterior (re-sella con su token), la decisión
     exige el token propio y la limpieza solo borra el sello propio. Un abono
     ya COMPROMETIDO (aprobado con sello, cierre pendiente) bloquea que el
     movimiento respalde una segunda orden.
CB05 (alta)    La reversión monetaria y su plan persistente exigen la MISMA
     generación bancaria capturada (`reconciliation.match_uid` en el sello,
     verificada atómicamente en el claim) ANTES de debitar o resetear: una
     reversión atrasada devuelve 409 sin tocar el ciclo nuevo.
CB08 (alta)    Un segundo nombre AUSENTE del diccionario ya no cuenta como
     apellido: solo el último token del titular (si no es nombre de pila
     conocido) o un apellido CONOCIDO intermedio son evidencia fiable.
     'JOSE YUNIER' ya no aprueba automáticamente 'JOSE YUNIER PEREZ'.
"""
import asyncio
import os
import types
import uuid

import pytest
from pymongo import MongoClient

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

UID = "user_test_vip01"
MARK = "iter302"
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
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class _Sandbox:
    def setup_method(self, _):
        db = _db()
        self._orig = db.users.find_one(
            {"user_id": UID},
            {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1}) or {}
        db.users.update_one({"user_id": UID},
                            {"$set": {"vip_balances.USDT": 0.0}})

    def teardown_method(self, _):
        db = _db()
        db.vip_batch_items.delete_many({"id": {"$regex": f"^vitem_{MARK}"}})
        db.vip_batches.delete_many({"id": {"$regex": f"^vb_{MARK}"}})
        db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
        db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
        db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
        db.users.update_one({"user_id": UID}, {"$pull": {
            "applied_credit_ops": {"$regex": MARK}}})
        db.users.update_one({"user_id": UID}, {"$set": {
            "vip_balances": self._orig.get("vip_balances") or {},
            "vip_balance_usd": float(self._orig.get("vip_balance_usd") or 0.0)}})

    def _mk_item(self, **extra):
        iid = f"vitem_{MARK}_{uuid.uuid4().hex[:8]}"
        doc = {"id": iid, "batch_id": f"vb_{MARK}_x", "vip_user_id": UID,
               "status": "pending", "from_code": "USD", "to_code": "USDT",
               "amount": 100.0, "amount_to": 100.0, "rate_applied": 1.0,
               "holder_name": "Persona Prueba", "created_at": OLD_TS}
        doc.update(extra)
        _db().vip_batch_items.insert_one(dict(doc))
        return iid

    def _mk_tx(self, **extra):
        tid = f"tx_{MARK}_{uuid.uuid4().hex[:8]}"
        doc = {"id": tid, "status": "manual_review", "direction": "credit",
               "amount": 100.0, "currency": "USD", "candidates": [],
               "sender_name": "Persona Prueba",
               "transaction_date": "2026-01-01", "created_at": OLD_TS,
               "updated_at": OLD_TS}
        doc.update(extra)
        _db().bank_transactions.insert_one(dict(doc))
        return tid

    def _set_usdt(self, amount, uid=UID):
        _db().users.update_one({"user_id": uid},
                               {"$set": {"vip_balances.USDT": float(amount)}})


# ======================================================================
# CB03 — vip_claim_fault: propiedad del intento hasta decisión y crédito
# ======================================================================
class TestCB03VipClaimFault(_Sandbox):
    def test_takeover_plus_transient_failure_never_double_credits(self):
        """Reproducción EXACTA del auditor: ítem VIP A pendiente, ítem B
        pendiente, UN abono de 100 USD, dos solicitudes superpuestas hacia A
        (la 2ª toma la reserva por el sello preparatorio) y un fallo
        transitorio de escritura antes de que la 2ª apruebe. El crédito total
        debe ser como máximo 100 USDT."""
        self._set_usdt(0)
        item_a, item_b = self._mk_item(), self._mk_item()
        tx = self._mk_tx()

        async def flow():
            import routes.reconciliation as recon
            import services.reconciliation_matcher as rm
            from fastapi import HTTPException
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            real_apply = rm.apply_item_decision
            started1, resume1 = asyncio.Event(), asyncio.Event()
            calls = {"n": 0}

            async def gated_apply(item_id, decision, staff, admin_note="",
                                  recon_attempt_token=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    # solicitud 1: pausa JUSTO ANTES de la actualización que
                    # aprueba el ítem (paso 1 del auditor).
                    started1.set()
                    await asyncio.wait_for(resume1.wait(), timeout=20)
                    return await real_apply(
                        item_id, decision, staff, admin_note=admin_note,
                        recon_attempt_token=recon_attempt_token)
                # solicitud 2: fallo transitorio de escritura antes de
                # aprobar (paso 3 del auditor).
                raise RuntimeError("transient write failure (injected)")

            rm.apply_item_decision = gated_apply
            req = types.SimpleNamespace(client=None)

            async def confirm(order_id):
                try:
                    await recon.confirm_match(
                        tx, types.SimpleNamespace(order_id=order_id), req)
                    return 200
                except HTTPException as ex:
                    return ex.status_code

            try:
                task1 = asyncio.create_task(confirm(item_a))
                await asyncio.wait_for(started1.wait(), timeout=20)
                # solicitud 2: encuentra A pendiente con el sello y toma la
                # reserva de la solicitud 1 (paso 2) → fallo inyectado.
                code2 = await confirm(item_a)
                # la solicitud 1 continúa (paso 4).
                resume1.set()
                code1 = await task1
                rm.apply_item_decision = real_apply
                # confirmación de B (paso 5).
                code_b = await confirm(item_b)
            finally:
                rm.apply_item_decision = real_apply
                recon.require_permission = orig_perm
            return code1, code2, code_b

        code1, code2, code_b = _run(flow)
        assert code2 == 409, f"la solicitud con fallo inyectado debe dar 409: {code2}"
        assert code1 == 409, \
            f"el intento desplazado no puede aprobar ni acreditar: {code1}"
        assert _bal("USDT") == 100.0, \
            f"un abono de 100 USD → máximo 100 USDT, no {_bal('USDT')} (CB03)"
        db = _db()
        a = db.vip_batch_items.find_one({"id": item_a}, {"_id": 0})
        assert a["status"] == "pending", \
            "A no acreditó: su intento perdió la propiedad de la reserva"
        assert code_b == 200, f"B debe poder usar el movimiento liberado: {code_b}"
        txd = db.bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == item_b

    def test_committed_credit_blocks_second_target(self):
        """Criterio de cierre: si A ya COMPROMETIÓ el abono (aprobada con el
        sello del movimiento, cierre bancario pendiente), B queda bloqueada;
        el reintento de A completa el vínculo (recuperación legítima)."""
        self._set_usdt(100)  # abono de A ya comprometido
        tx = self._mk_tx()
        item_a = self._mk_item(
            status="approved",
            reconciliation={"bank_transaction_id": tx, "matched_at": _now(),
                            "auto": False, "attempt_token": "tokDEAD",
                            "match_uid": "uidA"})
        item_b = self._mk_item()

        async def flow():
            import routes.reconciliation as recon
            from fastapi import HTTPException
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            req = types.SimpleNamespace(client=None)
            try:
                try:
                    await recon.confirm_match(
                        tx, types.SimpleNamespace(order_id=item_b), req)
                    code_b = 200
                except HTTPException as ex:
                    code_b = ex.status_code
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=item_a), req)
                code_a = 200
            finally:
                recon.require_permission = orig_perm
            return code_b, code_a

        code_b, code_a = _run(flow)
        assert code_b == 409, \
            f"B debe quedar bloqueada si A ya comprometió el abono: {code_b}"
        assert code_a == 200, f"el reintento de A completa el cierre: {code_a}"
        txd = _db().bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == item_a
        assert _bal("USDT") == 100.0, "sin doble crédito en la recuperación"

    def test_interrupted_prestamp_recovery_still_works(self):
        """Recuperación legítima conservada: un intento murió tras reservar y
        pre-sellar (ítem aún pendiente) — un intento nuevo toma la reserva,
        desplaza el sello y completa el abono UNA sola vez."""
        self._set_usdt(0)
        tx = self._mk_tx()
        item_a = self._mk_item(
            reconciliation={"bank_transaction_id": tx, "matched_at": _now(),
                            "auto": False, "attempt_token": "tokDEAD",
                            "match_uid": "uidDEAD"})
        _db().bank_transactions.update_one(
            {"id": tx},
            {"$set": {"matching_claim": {"order_id": item_a, "at": _now(),
                                         "by": "crashed", "token": "tokDEAD"}}})

        async def flow():
            import routes.reconciliation as recon
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            req = types.SimpleNamespace(client=None)
            try:
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=item_a), req)
            finally:
                recon.require_permission = orig_perm
            return 200

        assert _run(flow) == 200
        assert _bal("USDT") == 100.0, "la recuperación abona exactamente una vez"
        db = _db()
        a = db.vip_batch_items.find_one({"id": item_a}, {"_id": 0})
        assert a["status"] == "approved"
        txd = db.bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched"
        assert txd["matched_order_id"] == item_a


# ======================================================================
# CB05 — stale_rollback_target_read: la reversión atrasada no debita
# ======================================================================
class TestCB05StaleRollbackGeneration(_Sandbox):
    def _mk_accum_order(self, tx_id, uid_gen, cycle=1):
        oid = f"ord_{MARK}_{uuid.uuid4().hex[:8]}"
        _db().orders.insert_one({
            "id": oid, "user_id": UID, "user_name": "Persona Prueba",
            "sender_name": "Persona Prueba", "status": "approved",
            "amount_from": 100.0, "amount_to": 100.0,
            "from_code": "USD", "to_code": "USDT",
            "accumulated_at": _now(), "accum_cycle": cycle,
            "reconciliation": {"bank_transaction_id": tx_id,
                               "matched_at": _now(), "auto": False,
                               "match_uid": uid_gen},
            "created_at": OLD_TS, "updated_at": OLD_TS})
        return oid

    def test_stale_rollback_rejected_before_debit(self):
        """Reproducción EXACTA: la reversión antigua capturó la generación 1
        del movimiento; entre sus lecturas, otra reversión completó ese ciclo
        y la orden fue RE-conciliada (generación 2, saldo 100). La solicitud
        atrasada debe devolver 409 SIN debitar los 100 USDT, sin resetear la
        orden y sin tocar el vínculo nuevo."""
        self._set_usdt(100)  # crédito del ciclo NUEVO (generación 2)
        tx = self._mk_tx(status="manual_matched", match_uid="gen2")
        oid = self._mk_accum_order(tx, "gen2", cycle=1)
        _db().bank_transactions.update_one(
            {"id": tx}, {"$set": {"matched_order_id": oid,
                                  "matched_kind": "order"}})

        async def flow():
            from routes.reconciliation import _rollback_accumulated_order_credit
            from db_client import db as adb
            from fastapi import HTTPException
            # la solicitud atrasada relee la orden (ya en el ciclo nuevo) —
            # exactamente el punto señalado por el auditor — pero su
            # generación capturada sigue siendo la vieja ('gen1').
            fresh = await adb.orders.find_one({"id": oid}, {"_id": 0})
            try:
                await _rollback_accumulated_order_credit(
                    fresh, tx, "reversión atrasada",
                    expected_match_uid="gen1")
                return 200
            except HTTPException as ex:
                return ex.status_code

        code = _run(flow)
        assert code == 409, f"la reversión atrasada debe rechazarse: {code}"
        assert _bal("USDT") == 100.0, \
            f"el débito atrasado no puede tocar el ciclo nuevo: {_bal('USDT')}"
        db = _db()
        o = db.orders.find_one({"id": oid}, {"_id": 0})
        assert o["status"] == "approved", "A conserva su estado aprobado"
        assert int(o.get("accum_cycle") or 0) == 1
        assert "rollback_pending" not in o, "sin plan de reversión residual"
        txd = db.bank_transactions.find_one({"id": tx}, {"_id": 0})
        assert txd["status"] == "manual_matched", "el vínculo nuevo se conserva"
        assert txd["match_uid"] == "gen2"

    def test_stale_vip_item_rollback_rejected_before_debit(self):
        """Misma garantía para ítems VIP: la generación capturada obsoleta
        recibe 409 antes de descontar el crédito del ciclo nuevo."""
        self._set_usdt(100)
        tx = self._mk_tx(status="manual_matched", match_uid="gen2")
        iid = self._mk_item(
            status="approved", decision_cycle=1,
            reconciliation={"bank_transaction_id": tx, "matched_at": _now(),
                            "auto": False, "match_uid": "gen2"})

        async def flow():
            from services.reconciliation_matcher import (
                rollback_batch_item_from_reconciliation)
            from db_client import db as adb
            from fastapi import HTTPException
            fresh = await adb.vip_batch_items.find_one({"id": iid}, {"_id": 0})
            try:
                await rollback_batch_item_from_reconciliation(
                    fresh, tx, ADMIN_ACTOR, "reversión atrasada",
                    expected_match_uid="gen1")
                return 200
            except HTTPException as ex:
                return ex.status_code

        code = _run(flow)
        assert code == 409, f"la reversión atrasada del ítem debe rechazarse: {code}"
        assert _bal("USDT") == 100.0
        it = _db().vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert it["status"] == "approved"
        assert "rollback_pending" not in it

    def test_legit_cycles_and_rollback_still_work_end_to_end(self):
        """Varios ciclos legítimos de aprobación/reversión siguen intactos:
        confirmar acredita, revertir debita (misma generación) y una segunda
        confirmación abre una generación nueva."""
        self._set_usdt(0)
        tx = self._mk_tx()
        iid = self._mk_item()

        async def flow():
            import routes.reconciliation as recon
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            req = types.SimpleNamespace(client=None)
            try:
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=iid), req)
                bal_after_confirm = _bal("USDT")
                uid1 = (_db().bank_transactions.find_one(
                    {"id": tx}, {"_id": 0})).get("match_uid")
                await recon.rollback_match(
                    tx, types.SimpleNamespace(reason="ciclo legítimo"), req)
                bal_after_rollback = _bal("USDT")
                await recon.confirm_match(
                    tx, types.SimpleNamespace(order_id=iid), req)
                uid2 = (_db().bank_transactions.find_one(
                    {"id": tx}, {"_id": 0})).get("match_uid")
            finally:
                recon.require_permission = orig_perm
            return bal_after_confirm, bal_after_rollback, uid1, uid2

        bal1, bal0, uid1, uid2 = _run(flow)
        assert bal1 == 100.0 and bal0 == 0.0, (bal1, bal0)
        assert uid1 and uid2 and uid1 != uid2, \
            "cada ciclo es una generación nueva compartida sello↔movimiento"
        it = _db().vip_batch_items.find_one({"id": iid}, {"_id": 0})
        assert it["status"] == "approved"
        assert (it.get("reconciliation") or {}).get("match_uid") == uid2, \
            "el sello del destino guarda la generación del cierre"
        assert _bal("USDT") == 100.0


# ======================================================================
# CB08 — unlisted_given_name: palabra ausente del diccionario ≠ apellido
# ======================================================================
class TestCB08UnlistedGivenName:
    def test_unlisted_given_name_is_not_surname_evidence(self):
        from services.reconciliation_matcher import surname_similarity
        # el caso exacto del auditor: YUNIER no está en el diccionario de
        # nombres — aun así NO demuestra el apellido (PEREZ).
        assert surname_similarity("JOSE YUNIER", "JOSE YUNIER PEREZ") < 0.75

    def test_permutations_and_initials_do_not_prove_surname(self):
        from services.reconciliation_matcher import surname_similarity
        for bank in ("YUNIER JOSE", "J YUNIER", "JOSE Y", "YUNIER"):
            assert surname_similarity(bank, "JOSE YUNIER PEREZ") < 0.75, bank
        # los casos MANUEL del informe anterior se conservan
        assert surname_similarity("MANUEL JOSE", "JOSE MANUEL PEREZ") < 0.75
        assert surname_similarity("JOSE MANUEL", "JOSE MANUEL PEREZ") < 0.75

    def test_legit_surname_matches_preserved(self):
        from services.reconciliation_matcher import surname_similarity
        # último token del titular (apellido real)
        assert surname_similarity("JOSE PEREZ", "JOSE YUNIER PEREZ") >= 0.75
        # apellido CONOCIDO en posición intermedia (dos apellidos)
        assert surname_similarity("MARIA GARCIA", "MARIA GARCIA LOPEZ") >= 0.75
        # typo OCR tolerado por el umbral
        assert surname_similarity("ANA GONSALES", "ANA GONZALEZ") >= 0.75

    def test_decide_sends_unlisted_given_name_to_review(self):
        """Flujo real de matching: la orden de 'JOSE YUNIER PEREZ' con el
        extracto 'JOSE YUNIER' (resto de criterios compatibles) NO se aprueba
        automáticamente — va a revisión con surname_mismatch."""
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        order = {"id": "o1", "kind": "order", "user_id": "uA",
                 "user_name": "JOSE YUNIER PEREZ",
                 "sender_name": "JOSE YUNIER PEREZ",
                 "amount_from": 100.0, "from_code": "USD",
                 "created_at": "2026-09-24T00:00:00+00:00",
                 "status": "pending", "payment_reference": ""}
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "JOSE YUNIER",
              "transaction_date": "2026-09-24"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "review", d
        assert "surname_mismatch" in (d.get("block_reasons") or [])

    def test_decide_still_autos_on_real_surname(self):
        """Control de coincidencia legítima: con el apellido real presente en
        el remitente, la aprobación automática se conserva."""
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        order = {"id": "o2", "kind": "order", "user_id": "uA",
                 "user_name": "JOSE YUNIER PEREZ",
                 "sender_name": "JOSE YUNIER PEREZ",
                 "amount_from": 100.0, "from_code": "USD",
                 "created_at": "2026-09-24T00:00:00+00:00",
                 "status": "pending", "payment_reference": ""}
        tx = {"id": "t2", "amount": 100.0, "currency": "USD",
              "sender_name": "JOSE YUNIER PEREZ",
              "transaction_date": "2026-09-24"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "auto", d


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
