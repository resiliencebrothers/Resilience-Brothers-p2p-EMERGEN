"""iter319 — dos variantes concurrentes de generación en las escrituras nuevas.

CB10 (CRÍTICA): una reversión ANTIGUA libera la reserva económica que ya protege
otra conciliación del MISMO movimiento en un ciclo posterior, permitiendo un
segundo crédito de otra representación sin override explícito (200 USDT por un
único pago de 100 USD).
Fix (v5): la reserva lleva el TOKEN DE CICLO (`match_uid`); una reconfirmación lo
RENUEVA y una reversión solo libera el ciclo que deshizo.

DR02 (MEDIA): dos cambios de evidencia rechazados cuyas reparaciones terminan en
orden inverso hacen RETROCEDER la secuencia de la reserva (`movement_seq` 3 → 2),
y los reintentos válidos vuelven a recibir 409.
Fix (v9): la reparación es MONOTÓNICA (`movement_seq < moved_seq`): una escritura
antigua no puede disminuir la generación.

Harness: proxy de base de datos (`_HookDb`) que intercepta UN método de UNA
colección para pausar una tarea concreta antes de una escritura atómica — sin
dividir la escritura por dentro — reproduciendo el orden inverso real.
"""
import asyncio
import os
import types
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient
from fastapi import HTTPException

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

MARK = "iter319"
CLI_DR = "uiter319dr"
CLI_CB = "uiter319cb"
ADMIN_ACTOR = {"user_id": "user_test_admin01", "role": "admin",
               "email": "admin.test@resilience.com", "name": "Admin Test"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


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


# ───────────────────────── proxy de base de datos ──────────────────────────
class _HookColl:
    """Envuelve una colección Motor: intercepta UN método; el resto pasa igual."""
    def __init__(self, real, method, hook):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_method", method)
        object.__setattr__(self, "_hook", hook)

    def __getattr__(self, name):
        real = object.__getattribute__(self, "_real")
        if name == object.__getattribute__(self, "_method"):
            hook = object.__getattribute__(self, "_hook")

            async def _wrapper(*a, **k):
                return await hook(real, *a, **k)
            return _wrapper
        return getattr(real, name)


class _HookDb:
    """Envuelve la base: una colección hookeada; las demás, directas."""
    def __init__(self, real, coll_name, method, hook):
        self._real = real
        self._coll_name = coll_name
        self._coll = _HookColl(real[coll_name], method, hook)

    def __getattr__(self, name):
        if name == self._coll_name:
            return self._coll
        return getattr(self._real, name)

    def __getitem__(self, name):
        if name == self._coll_name:
            return self._coll
        return self._real[name]


# ══════════════════════════════ DR02 ═══════════════════════════════════════
def _seed_dr():
    db = _db()
    db.users.update_one(
        {"user_id": CLI_DR},
        {"$set": {"user_id": CLI_DR, "email": f"{CLI_DR}@t.com", "name": CLI_DR,
                  "role": "vip", "vip_balances": {"USDT": 0.0},
                  "vip_balance_usd": 0.0, "applied_credit_ops": []}},
        upsert=True)
    common = {
        "user_id": CLI_DR, "user_email": f"{CLI_DR}@t.com", "user_name": CLI_DR,
        "user_role": "vip", "currency": "USDT", "amount": 100.0,
        "method": "crypto", "network": "BEP20", "tx_hash": f"{MARK}_dr_hash",
        "status": "pending", "created_at": _now(), "updated_at": _now()}
    db.deposits.insert_one({**common, "id": f"dep{MARK}b"})
    db.deposits.insert_one({**common, "id": f"dep{MARK}a"})


def _cleanup_dr():
    db = _db()
    db.deposits.delete_many({"id": {"$regex": f"^dep{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": f"{MARK}_dr"}})
    db.users.delete_many({"user_id": CLI_DR})


class TestDR02MonotonicRepair:
    def setup_method(self, _):
        _cleanup_dr()

    def teardown_method(self, _):
        _cleanup_dr()

    def test_out_of_order_repairs_do_not_lower_generation(self):
        _seed_dr()
        a_id, b_id = f"dep{MARK}a", f"dep{MARK}b"

        async def flow():
            import routes.deposits as dep
            real_db = dep.db
            staff = await real_db.users.find_one(
                {"user_id": "user_test_admin01"}, {"_id": 0}) or {
                "user_id": "user_test_admin01", "role": "admin",
                "email": "admin.test@resilience.com"}

            dB = await real_db.deposits.find_one({"id": b_id}, {"_id": 0})
            await dep._do_confirm_deposit(dict(dB), staff, "log:1")
            dA = await real_db.deposits.find_one({"id": a_id}, {"_id": 0})
            await dep._claim_crypto_evidence(dict(dA), "log:0")

            paused = asyncio.Event()
            release = asyncio.Event()

            async def hook(real_coll, flt, upd, *a, **k):
                sets = (upd or {}).get("$set", {})
                name = asyncio.current_task().get_name()
                # Pausa la reparación del move #1 (generación 2) ANTES de escribir,
                # para que el move #2 (generación 3) repare primero a 3.
                if sets.get("movement_seq") == 2 and name == "moveA":
                    paused.set()
                    await release.wait()
                return await real_coll.update_one(flt, upd, *a, **k)

            dep.db = _HookDb(real_db, "crypto_evidence_claims", "update_one",
                             hook)
            errs = {}
            try:
                async def move(mid):
                    try:
                        await dep._claim_crypto_evidence(dict(dA), mid)
                        return 200
                    except HTTPException as e:
                        return e.status_code

                move_a = asyncio.create_task(move("log:1"), name="moveA")
                await paused.wait()
                # move #2: consume generación 3 y repara la reserva vigente a 3.
                errs["second"] = await move("log:1")
                # Reanuda la reparación tardía del move #1 (generación 2).
                release.set()
                errs["first"] = await move_a
            finally:
                dep.db = real_db

            rA = await dep._do_confirm_deposit(dict(dA), staff, "log:0")
            return errs, rA

        errs, rA = _run(flow)
        assert errs["second"] == 409 and errs["first"] == 409, errs
        assert isinstance(rA, dict) and rA.get("status") == "confirmed", rA

        db = _db()
        active = db.crypto_evidence_claims.find_one(
            {"deposit_id": a_id, "superseded": {"$ne": True}},
            {"_id": 0, "movement_id": 1, "movement_seq": 1})
        # La reparación tardía (gen 2) NO hizo retroceder la generación: sigue en 3.
        assert active["movement_id"] == "log:0"
        assert active["movement_seq"] == 3, active
        depA = db.deposits.find_one({"id": a_id})
        assert depA["evidence_claim_seq_next"] == 3
        assert depA["status"] == "confirmed"
        # A y B = movimientos distintos → saldo total 200 USDT.
        u = db.users.find_one({"user_id": CLI_DR}, {"_id": 0, "vip_balances": 1})
        assert float((u.get("vip_balances") or {}).get("USDT") or 0) == 200.0


# ══════════════════════════════ CB10 ═══════════════════════════════════════
def _seed_cb_user():
    _db().users.update_one(
        {"user_id": CLI_CB},
        {"$set": {"user_id": CLI_CB, "email": f"{CLI_CB}@t.com", "name": CLI_CB,
                  "role": "vip", "vip_balances": {}, "applied_credit_ops": []}},
        upsert=True)


def _cleanup_cb():
    db = _db()
    db.orders.delete_many({"id": {"$regex": f"^ord_{MARK}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{MARK}"}})
    db.bank_statement_imports.delete_many({"id": {"$regex": f"^imp_{MARK}"}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})
    db.economic_credit_claims.delete_many({"tx_id": {"$regex": f"^tx_{MARK}"}})
    db.users.delete_many({"user_id": CLI_CB})


def _bal_cb(code="USDT"):
    u = _db().users.find_one({"user_id": CLI_CB}, {"_id": 0, "vip_balances": 1})
    return float(((u or {}).get("vip_balances") or {}).get(code) or 0.0)


def _mk_order(suffix, amount=100.0):
    oid = f"ord_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().orders.insert_one({
        "id": oid, "user_id": CLI_CB, "user_name": CLI_CB, "user_role": "vip",
        "status": "pending", "from_code": "USD", "to_code": "USDT",
        "amount_from": float(amount), "amount": float(amount),
        "amount_to": float(amount), "rate_applied": 1.0,
        "delivery_method": "accumulate", "holder_name": "Persona Prueba",
        "sender_name": "Persona Prueba",
        "created_at": _now(), "updated_at": _now()})
    return oid


def _mk_import(suffix):
    iid = f"imp_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().bank_statement_imports.insert_one({
        "id": iid, "processing_status": "processed", "currency": "USD",
        "bank_name": "Banco Prueba", "bank_account_id": None,
        "original_file_name": "extracto.pdf", "stored_file_url": "",
        "created_at": _now(), "updated_at": _now()})
    return iid


def _mk_tx(suffix, import_id, amount=100.0):
    tid = f"tx_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().bank_transactions.insert_one({
        "id": tid, "status": "unmatched", "direction": "credit",
        "amount": float(amount), "currency": "USD", "candidates": [],
        "bank_account_id": None, "sender_name": "Persona Prueba",
        "description": "Transferencia Persona Prueba",
        "transaction_date": _today(), "statement_import_id": import_id,
        "fingerprint": f"fp_{uuid.uuid4().hex}",
        "fingerprint_original": f"fpo_{suffix}_{uuid.uuid4().hex[:8]}",
        "created_at": _now(), "updated_at": _now()})
    return tid


def _econ_key_for(tx_id):
    import services.reconciliation_matcher as rm
    return rm._economic_identity_key(
        _db().bank_transactions.find_one({"id": tx_id}, {"_id": 0}))


class TestCB10CycleOwnership:
    def setup_method(self, _):
        _cleanup_cb()
        _seed_cb_user()

    def teardown_method(self, _):
        _cleanup_cb()

    def test_old_rollback_cannot_release_new_cycle_reservation(self):
        order_a = _mk_order("A")
        imp1 = _mk_import("1")
        tx_a = _mk_tx("A", imp1)
        econ_key = _econ_key_for(tx_a)

        async def flow():
            import routes.reconciliation as recon
            import services.reconciliation_matcher as rm
            real_db = rm.db

            async def automatch(tx_id):
                tx_doc = await real_db.bank_transactions.find_one(
                    {"id": tx_id}, {"_id": 0})
                return await rm.run_matching(
                    {"currency": "USD", "bank_account_id": None}, [tx_doc])

            # 1) Conciliación automática de A: crédito 100 + reserva (ciclo uid1).
            counts = await automatch(tx_a)
            assert counts.get("auto") == 1, counts
            txA = await real_db.bank_transactions.find_one(
                {"id": tx_a}, {"_id": 0, "match_uid": 1})
            old_uid = txA["match_uid"]

            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            paused = asyncio.Event()
            release = asyncio.Event()

            async def hook(real_coll, *a, **k):
                # Pausa la reversión ANTIGUA justo antes de borrar la reserva.
                if asyncio.current_task().get_name() == "oldRollback":
                    paused.set()
                    await release.wait()
                return await real_coll.delete_one(*a, **k)

            rm.db = _HookDb(real_db, "economic_credit_claims", "delete_one",
                            hook)
            req = types.SimpleNamespace(client=None)
            try:
                async def do_rollback():
                    try:
                        await recon.rollback_match(
                            tx_a,
                            types.SimpleNamespace(reason="reversion antigua"),
                            req)
                        return 200
                    except HTTPException as e:
                        return e.status_code

                rb_task = asyncio.create_task(do_rollback(), name="oldRollback")
                await paused.wait()
                # La reversión ya revirtió crédito/orden/vínculo; falta soltar la
                # reserva. El MISMO movimiento se reconcilia manualmente en un
                # CICLO NUEVO (uid2): renueva el token de la reserva.
                try:
                    await recon.confirm_match(
                        tx_a, recon.ConfirmPayload(order_id=order_a), req)
                    reconf = 200
                except HTTPException as e:
                    reconf = e.status_code
                new_uid = (await real_db.bank_transactions.find_one(
                    {"id": tx_a}, {"_id": 0, "match_uid": 1}))["match_uid"]
                # Reanuda la reversión antigua: su liberación (uid1) NO debe
                # borrar la reserva que ahora protege el ciclo nuevo (uid2).
                release.set()
                rb_code = await rb_task
            finally:
                rm.db = real_db
                recon.require_permission = orig_perm
            return old_uid, new_uid, reconf, rb_code

        old_uid, new_uid, reconf, rb_code = _run(flow)
        assert reconf == 200, "la reconfirmación del ciclo nuevo acredita"
        assert rb_code == 200, "la reversión antigua termina su cierre"
        assert old_uid and new_uid and old_uid != new_uid, (old_uid, new_uid)

        db = _db()
        claim = db.economic_credit_claims.find_one({"_id": econ_key})
        # La reserva SOBREVIVE a la reversión antigua y pertenece al ciclo nuevo.
        assert claim is not None, "la reversión antigua no debe liberar el ciclo nuevo"
        assert claim.get("tx_id") == tx_a
        assert claim.get("match_uid") == new_uid, claim
        assert _bal_cb("USDT") == 100.0, "crédito único vivo"

        # Cierre: la representación XLS (otra huella, misma identidad económica)
        # recibe 409 SIN override y el saldo permanece en 100.
        async def xls_flow():
            import routes.reconciliation as recon
            order_b = _mk_order("B")
            imp_xls = _mk_import("XLS")
            tx_xls = _mk_tx("XLS", imp_xls)
            orig_perm = recon.require_permission
            recon.require_permission = _stub_permission
            try:
                try:
                    await recon.confirm_match(
                        tx_xls, recon.ConfirmPayload(order_id=order_b),
                        types.SimpleNamespace(client=None))
                    return 200
                except HTTPException as e:
                    return e.status_code
            finally:
                recon.require_permission = orig_perm

        xls_code = _run(xls_flow)
        assert xls_code == 409, "sin override, la reimportación no acredita"
        assert _bal_cb("USDT") == 100.0, "el saldo permanece en 100 USDT"
