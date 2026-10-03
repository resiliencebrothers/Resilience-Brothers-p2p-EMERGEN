"""iter316 — DR02 v7 (MEDIA): la asignación de generación NO debe mover la
reserva de un depósito que ya salió de pendiente.

El informe (sobre iter314/315) mostró que, aunque la comparación final de
generación (`evidence_claim_seq_next == my_seq`) corrige el caso donde B sella
antes de confirmar, el incremento de generación (`_next_evidence_seq`) filtraba
SOLO por ID; la comprobación de estado pendiente era una lectura SEPARADA y
previa. Así:

  A reserva/sella log:0 (gen 1) y se pausa antes de confirmar.
  B lee que el depósito está pendiente y se dispone a mover la reserva a log:1;
  se pausa ANTES del find_one_and_update del contador.
  A confirma log:0 y acredita 100.
  B ejecuta el incremento (sin exigir pending) → modifica el depósito YA
  confirmado (generación → 2), crea la reserva log:1 y sustituye la de log:0; su
  confirmación recibe 409. Estado final inconsistente: evidencia confirmada
  log:0 pero reserva activa log:1.

Fix: `_next_evidence_seq` incrementa SOLO si el depósito sigue `pending`
(atómico); si no es elegible devuelve None y `_claim_crypto_evidence` rechaza el
intento ANTES de crear/sustituir reservas. CIERRE: si A confirma primero, B
recibe 409 sin mover la reserva y la identidad permanece en log:0.

Infra: un loop por método (Motor se enlaza al loop que lo usa).
"""
import asyncio
import os
from datetime import datetime, timezone

from pymongo import MongoClient

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

MARK = "iter316"
CLIENT = "uiter316dr02"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(timezone.utc).isoformat()


class _CollProxy:
    def __init__(self, real, on_update):
        self._real = real
        self._on_update = on_update

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def update_one(self, filt, update, *a, **k):
        await self._on_update(filt, update)
        return await self._real.update_one(filt, update, *a, **k)


class _DbProxy:
    def __init__(self, real, on_update):
        self._real = real
        self._on_update = on_update

    def __getattr__(self, name):
        if name == "deposits":
            return _CollProxy(self._real.deposits, self._on_update)
        return getattr(self._real, name)


def teardown_module():
    _cleanup()


def _cleanup():
    db = _db()
    db.deposits.delete_many({"id": {"$regex": f"^dep{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.users.delete_many({"user_id": CLIENT})


class TestDR02GenerationRequiresPending:
    def setup_method(self, _):
        _cleanup()

    def teardown_method(self, _):
        _cleanup()

    def test_generation_move_blocked_after_deposit_confirmed(self):
        """A confirma primero; cuando B intenta mover la reserva, el incremento
        de generación NO encuentra el depósito pendiente → B recibe 409 SIN
        mover la reserva. La evidencia confirmada y la reserva activa permanecen
        en log:0; crédito único de 100."""
        _db().users.update_one(
            {"user_id": CLIENT},
            {"$set": {"user_id": CLIENT, "email": f"{CLIENT}@t.com",
                      "name": CLIENT, "role": "vip",
                      "vip_balances": {"USDT": 0.0}, "vip_balance_usd": 0.0,
                      "applied_credit_ops": []}}, upsert=True)
        dep_id = f"dep{MARK}"
        _db().deposits.insert_one({
            "id": dep_id, "user_id": CLIENT, "user_email": f"{CLIENT}@t.com",
            "user_name": CLIENT, "user_role": "vip", "currency": "USDT",
            "amount": 100.0, "method": "crypto", "network": "BEP20",
            "tx_hash": f"{MARK}_hash", "status": "pending",
            "created_at": _now(), "updated_at": _now()})

        async def flow():
            import routes.deposits as dep
            real_db = dep.db
            real_next_seq = dep._next_evidence_seq
            staff = await real_db.users.find_one(
                {"user_id": "user_test_admin01"}, {"_id": 0}) or {
                "user_id": "user_test_admin01", "role": "admin",
                "email": "admin.test@resilience.com"}
            a_confirm_reached, a_confirm_gate = asyncio.Event(), asyncio.Event()
            b_seq_reached, b_seq_gate = asyncio.Event(), asyncio.Event()

            async def on_update(filt, update):
                sets = update.get("$set", {}) if isinstance(update, dict) else {}
                task = asyncio.current_task().get_name()
                if task == "A" and sets.get("status") == "confirmed":
                    a_confirm_reached.set()
                    await a_confirm_gate.wait()

            async def gated_next_seq(deposit_id, require_pending=True):
                # Pausa SOLO el incremento de B (su 'move'), antes de ejecutarlo.
                if asyncio.current_task().get_name() == "B":
                    b_seq_reached.set()
                    await b_seq_gate.wait()
                return await real_next_seq(deposit_id, require_pending)

            dep.db = _DbProxy(real_db, on_update)
            dep._next_evidence_seq = gated_next_seq
            try:
                dA = await real_db.deposits.find_one({"id": dep_id}, {"_id": 0})
                tA = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dA), staff, "log:0"), name="A")
                await asyncio.wait_for(a_confirm_reached.wait(), 15)
                dB = await real_db.deposits.find_one({"id": dep_id}, {"_id": 0})
                tB = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dB), staff, "log:1"), name="B")
                await asyncio.wait_for(b_seq_reached.wait(), 15)
                # A confirma primero, con B pausado antes de su incremento.
                a_confirm_gate.set()
                rA = (await asyncio.gather(tA, return_exceptions=True))[0]
                # B reanuda: su incremento ya no halla el depósito pendiente.
                b_seq_gate.set()
                rB = (await asyncio.gather(tB, return_exceptions=True))[0]
                return rA, rB
            finally:
                dep.db = real_db
                dep._next_evidence_seq = real_next_seq

        from fastapi import HTTPException
        rA, rB = _run(flow())
        assert isinstance(rA, dict) and rA.get("status") == "confirmed", rA
        assert isinstance(rB, HTTPException) and rB.status_code == 409, rB

        db = _db()
        fresh = db.deposits.find_one({"id": dep_id})
        active = db.crypto_evidence_claims.find_one(
            {"deposit_id": dep_id, "superseded": {"$ne": True}},
            {"_id": 0, "movement_id": 1})
        u = db.users.find_one({"user_id": CLIENT},
                              {"_id": 0, "vip_balances": 1})
        log1 = db.crypto_evidence_claims.find_one(
            {"deposit_id": dep_id, "movement_id": "log:1"})
        assert fresh["status"] == "confirmed"
        assert fresh["evidence_movement_id"] == "log:0"
        assert fresh["evidence_claim_movement"] == "log:0"
        assert (active or {}).get("movement_id") == "log:0", \
            "la identidad permanece en log:0: B no movió la reserva"
        assert log1 is None, "B jamás creó la reserva log:1 sobre un confirmado"
        assert float((u.get("vip_balances") or {}).get("USDT") or 0) == 100.0
