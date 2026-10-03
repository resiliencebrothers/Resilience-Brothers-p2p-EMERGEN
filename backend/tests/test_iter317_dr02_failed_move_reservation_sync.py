"""iter317 — DR02 v8 (MEDIA): un intento de MOVER la evidencia que debe
rechazarse NO puede bloquear la confirmación válida de la reserva vigente.

Informe reproducido (NO requiere fallo de base de datos; basta un cambio de
evidencia que deba rechazarse):

  El depósito B ya confirmó el movimiento log:1 de una transacción.
  A reserva el movimiento DISTINTO log:0 de esa transacción (generación 1) y
  espera antes de confirmar.
  Otro intento de A trata de cambiar su evidencia a log:1 → incrementa el
  contador de A a 2, pero recibe 409 porque ese movimiento pertenece a B.
  La reserva vigente de A sigue siendo log:0, pero su `movement_seq` quedó en 1
  mientras el contador `evidence_claim_seq_next` avanzó a 2.
  Resultado del bug: al reconfirmar log:0, `_claim` devuelve secuencia 1, pero
  el filtro de confirmación exige `evidence_claim_seq_next == my_seq` → 2 ≠ 1 →
  409 para siempre. A queda pending, con reserva activa log:0 y SIN crédito; el
  saldo total era 100 USDT (solo el depósito B).

Fix (v8): cuando el move a una identidad AJENA falla, re-sincronizamos la
generación de la reserva que SIGUE vigente (`movement_seq`) con el contador ya
consumido, sin decrementar nada y solo si no fue superada por un move legítimo
concurrente. CIERRE: el intento inválido SIGUE recibiendo 409, pero A puede
confirmar log:0 UNA sola vez; ambos depósitos representan movimientos distintos
y el saldo total pasa a 200 USDT.

Infra: un loop por método (Motor se enlaza al loop que lo usa).
"""
import asyncio
import os
from datetime import datetime, timezone

from pymongo import MongoClient
from fastapi import HTTPException

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

MARK = "iter317"
CLIENT = "uiter317dr02"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(timezone.utc).isoformat()


def teardown_module():
    _cleanup()


def _cleanup():
    db = _db()
    db.deposits.delete_many({"id": {"$regex": f"^dep{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.users.delete_many({"user_id": CLIENT})


class TestDR02FailedMoveReservationSync:
    def setup_method(self, _):
        _cleanup()

    def teardown_method(self, _):
        _cleanup()

    def _seed(self):
        db = _db()
        db.users.update_one(
            {"user_id": CLIENT},
            {"$set": {"user_id": CLIENT, "email": f"{CLIENT}@t.com",
                      "name": CLIENT, "role": "vip",
                      "vip_balances": {"USDT": 0.0}, "vip_balance_usd": 0.0,
                      "applied_credit_ops": []}}, upsert=True)
        common = {
            "user_id": CLIENT, "user_email": f"{CLIENT}@t.com",
            "user_name": CLIENT, "user_role": "vip", "currency": "USDT",
            "amount": 100.0, "method": "crypto", "network": "BEP20",
            "tx_hash": f"{MARK}_hash", "status": "pending",
            "created_at": _now(), "updated_at": _now()}
        db.deposits.insert_one({**common, "id": f"dep{MARK}b"})
        db.deposits.insert_one({**common, "id": f"dep{MARK}a"})

    def test_failed_move_does_not_block_valid_confirmation(self):
        self._seed()
        a_id, b_id = f"dep{MARK}a", f"dep{MARK}b"

        async def flow():
            import routes.deposits as dep
            db = dep.db
            staff = await db.users.find_one(
                {"user_id": "user_test_admin01"}, {"_id": 0}) or {
                "user_id": "user_test_admin01", "role": "admin",
                "email": "admin.test@resilience.com"}

            # 1) B confirma el movimiento log:1 (reserva + crédito de 100).
            dB = await db.deposits.find_one({"id": b_id}, {"_id": 0})
            rB = await dep._do_confirm_deposit(dict(dB), staff, "log:1")

            # 2) A reserva el movimiento DISTINTO log:0 y espera (sin confirmar).
            dA = await db.deposits.find_one({"id": a_id}, {"_id": 0})
            seq0 = await dep._claim_crypto_evidence(dict(dA), "log:0")

            # 3) Otro intento de A intenta cambiar su evidencia a log:1 (de B):
            #    debe recibir 409 (identidad ajena) — SIN liberar/mover nada.
            move_err = None
            try:
                await dep._claim_crypto_evidence(dict(dA), "log:1")
            except HTTPException as e:
                move_err = e

            # 4) A reconfirma con su evidencia VÁLIDA log:0: debe acreditar 100.
            rA = await dep._do_confirm_deposit(dict(dA), staff, "log:0")

            # 5) Un segundo intento de confirmar A (ya confirmado) → 409:
            #    demuestra que el crédito ocurre UNA sola vez.
            dbl_err = None
            try:
                await dep._do_confirm_deposit(dict(dA), staff, "log:0")
            except HTTPException as e:
                dbl_err = e
            return rB, seq0, move_err, rA, dbl_err

        rB, seq0, move_err, rA, dbl_err = _run(flow())

        # B quedó confirmado con log:1.
        assert isinstance(rB, dict) and rB.get("status") == "confirmed", rB
        # El intento inválido de mover a log:1 (ajeno) SIGUE recibiendo 409.
        assert isinstance(move_err, HTTPException), move_err
        assert move_err.status_code == 409, move_err
        # A confirmó su evidencia válida log:0 exactamente una vez.
        assert isinstance(rA, dict) and rA.get("status") == "confirmed", rA
        assert isinstance(dbl_err, HTTPException) and dbl_err.status_code == 409

        db = _db()
        fa = db.deposits.find_one({"id": a_id})
        fb = db.deposits.find_one({"id": b_id})
        assert fa["status"] == "confirmed"
        assert fa["evidence_movement_id"] == "log:0"
        assert fa["evidence_claim_movement"] == "log:0"
        assert fb["evidence_movement_id"] == "log:1"

        # Reserva vigente de A permanece en log:0 (su identidad válida).
        active = db.crypto_evidence_claims.find_one(
            {"deposit_id": a_id, "superseded": {"$ne": True}},
            {"_id": 0, "movement_id": 1})
        assert (active or {}).get("movement_id") == "log:0", active
        # A nunca creó una reserva log:1 (esa identidad es de B).
        a_log1 = db.crypto_evidence_claims.find_one(
            {"deposit_id": a_id, "movement_id": "log:1"})
        assert a_log1 is None, "A no puede reclamar el movimiento de B"

        # Ambos depósitos = movimientos distintos → saldo total 200 USDT.
        u = db.users.find_one({"user_id": CLIENT},
                              {"_id": 0, "vip_balances": 1})
        assert float((u.get("vip_balances") or {}).get("USDT") or 0) == 200.0
