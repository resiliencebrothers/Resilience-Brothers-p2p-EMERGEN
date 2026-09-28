"""iter306 — Verificación de Depósitos (residual concurrente de DR02, informe
91b879e re-reportado): "Al recuperar una reserva vencida, dos órdenes pueden
acreditar 200 USDT respaldados por un único abono de 100 USD, con tasa 1:1".

Causa raíz: la "transición controlada" de `_claim_crypto_evidence` REESCRIBÍA
la `claim_key` en el sitio al reanudar con OTRO ID de movimiento. Eso LIBERABA
la identidad vieja (`log:0`) del índice único, de modo que un SEGUNDO depósito
con el mismo hash podía reclamar ese `log:0` liberado y acreditar otros 100
USDT — dos abonos con un solo pago on-chain.

Fix (DR02 v4): la identidad reservada es INDIVISIBLE. Al mover el movimiento se
INSERTA la nueva reserva y la anterior queda como LÁPIDA (`superseded`): su
clave permanece ocupando el índice único, así ningún otro depósito puede
reclamar un movimiento que una confirmación viva aún podría consumir. Los
movimientos REALMENTE nuevos (jamás reservados) se siguen aceptando.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api"
MARK = "iter306"

CLI_ID = "user_test_cli306"
CLI_TOKEN = f"test_session_{uuid.uuid4().hex}"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


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


def _now():
    return datetime.now(timezone.utc).isoformat()


def _bal(uid, code):
    u = _db().users.find_one({"user_id": uid},
                             {"vip_balances": 1, "vip_balance_usd": 1}) or {}
    total = float((u.get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        total += float(u.get("vip_balance_usd") or 0.0)
    return total


def _set_bal(uid, code, amount):
    sets = {f"vip_balances.{code}": float(amount)}
    if code == "USD":
        sets["vip_balance_usd"] = 0.0
    _db().users.update_one({"user_id": uid}, {"$set": sets})


def setup_module():
    db = _db()
    db.users.update_one(
        {"user_id": CLI_ID},
        {"$set": {"user_id": CLI_ID, "email": f"{CLI_ID}@test.com",
                  "name": CLI_ID, "role": "vip", "vip_balances": {},
                  "applied_credit_ops": []}},
        upsert=True)
    db.user_sessions.update_one(
        {"session_token": CLI_TOKEN},
        {"$set": {"session_token": CLI_TOKEN, "user_id": CLI_ID,
                  "expires_at": "2099-01-01T00:00:00+00:00"}},
        upsert=True)
    db.currencies.update_one(
        {"code": "USDT"},
        {"$setOnInsert": {"code": "USDT", "name": "Tether", "type": "crypto",
                          "is_active": True, "delivery_methods": ["crypto"]}},
        upsert=True)
    _cleanup()


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": CLI_ID})
    db.user_sessions.delete_many({"session_token": CLI_TOKEN})
    _cleanup()


def _cleanup():
    db = _db()
    db.deposits.delete_many({"user_id": CLI_ID})
    db.deposits.delete_many({"tx_hash": {"$regex": MARK}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})


def _mk_deposit(dep_id, tx_hash, amount=100.0, currency="USDT",
                network="BEP20", status="pending"):
    doc = {
        "id": dep_id, "user_id": CLI_ID, "user_email": f"{CLI_ID}@test.com",
        "user_name": CLI_ID, "user_role": "vip", "currency": currency,
        "amount": float(amount), "method": "crypto", "cash_mode": None,
        "network": network, "usdt_equivalent": None, "account_holder": None,
        "tx_hash": tx_hash, "proof_url": None, "note": None, "status": status,
        "admin_note": None, "reviewed_at": None, "reviewed_by": None,
        "created_at": _now(), "updated_at": _now(),
    }
    _db().deposits.insert_one(dict(doc))
    return doc


def _confirm(dep_id, movement_id=None):
    body = {"evidence_movement_id": movement_id} if movement_id else {}
    return requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                         headers=_h(ADMIN), json=body)


# ---------------------------------------------------------------------------
# Proxy de BD: barrera de concurrencia SOLO en `deposits.update_one` del sello
# final (idéntico patrón que iter305).
# ---------------------------------------------------------------------------
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

    def __getitem__(self, name):
        if name == "deposits":
            return _CollProxy(self._real["deposits"], self._on_update)
        return self._real[name]


async def _staff():
    from db_client import db as real_db
    staff = await real_db.users.find_one({"user_id": "user_test_admin01"},
                                         {"_id": 0})
    return staff or {"user_id": "user_test_admin01", "role": "admin",
                     "email": "admin.test@resilience.com"}


class TestDR02FreedMovementNotReclaimable:
    def test_freed_movement_after_move_not_reclaimable_by_other_deposit(self):
        """Los 6 pasos del informe: A reserva log:0 y se pausa antes del sello;
        una segunda confirmación VIVA de A mueve la reserva a log:1 y se pausa.
        Al reanudar, A (log:0) recibe 409 y A confirma con log:1 (+100). Un
        segundo depósito B con el MISMO hash intenta reclamar el log:0 que quedó
        liberado por el move: DEBE recibir 409 (identidad sellada como lápida)
        y el saldo permanece en 100 — nunca 200 con un solo abono."""
        h = f"{MARK}hash_freed"
        depA = _mk_deposit(f"dep_{MARK}_A", tx_hash=h)
        _set_bal(CLI_ID, "USDT", 0)

        async def race():
            import routes.deposits as dep
            real_db = dep.db
            staff = await _staff()
            reached = {"log:0": asyncio.Event(), "log:1": asyncio.Event()}
            gates = {"log:0": asyncio.Event(), "log:1": asyncio.Event()}

            async def on_update(filt, update):
                if isinstance(update, dict) \
                        and update.get("$set", {}).get("status") == "confirmed":
                    mv = filt.get("evidence_claim_movement")
                    if mv in reached:
                        reached[mv].set()
                        await gates[mv].wait()

            dep.db = _DbProxy(real_db, on_update)
            try:
                dA = await real_db.deposits.find_one({"id": depA["id"]},
                                                     {"_id": 0})
                t0 = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dA), staff, "log:0"))
                await asyncio.wait_for(reached["log:0"].wait(), 15)
                dA2 = await real_db.deposits.find_one({"id": depA["id"]},
                                                      {"_id": 0})
                t1 = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dA2), staff, "log:1"))
                await asyncio.wait_for(reached["log:1"].wait(), 15)
                gates["log:0"].set()
                r0 = (await asyncio.gather(t0, return_exceptions=True))[0]
                gates["log:1"].set()
                r1 = (await asyncio.gather(t1, return_exceptions=True))[0]
                return r0, r1
            finally:
                dep.db = real_db

        from fastapi import HTTPException
        r0, r1 = _run(race)
        assert isinstance(r0, HTTPException) and r0.status_code == 409, r0
        assert isinstance(r1, dict), r1

        fresh = _db().deposits.find_one({"id": depA["id"]})
        assert fresh["status"] == "confirmed"
        assert fresh["evidence_movement_id"] == "log:1"
        assert _bal(CLI_ID, "USDT") == 100.0, "un solo abono para el depósito A"

        # Núcleo del bug: el log:0 liberado por el move NO es reclamable por B.
        depB = _mk_deposit(f"dep_{MARK}_B", tx_hash=h)
        rb = _confirm(depB["id"], "log:0")
        assert rb.status_code == 409, \
            f"B no debe acreditar un movimiento liberado por el move: {rb.text}"
        fb = _db().deposits.find_one({"id": depB["id"]})
        assert fb["status"] == "pending", "B queda pendiente, no confirmado"
        assert _bal(CLI_ID, "USDT") == 100.0, \
            "jamás 200 USDT respaldados por un único abono de 100 USD"

    def test_genuinely_new_movement_still_accepted(self):
        """Regresión de la funcionalidad legítima: dos transferencias REALES
        distintas dentro de la misma transacción (movimientos nunca reservados)
        se siguen acreditando ambas. Solo se bloquean las identidades liberadas
        por un move (lápidas), no los movimientos genuinamente nuevos."""
        h = f"{MARK}hash_multi"
        depC = _mk_deposit(f"dep_{MARK}_C", tx_hash=h)
        depD = _mk_deposit(f"dep_{MARK}_D", tx_hash=h)
        _set_bal(CLI_ID, "USDT", 0)
        rc = _confirm(depC["id"], "mov:a")
        assert rc.status_code == 200, rc.text
        rd = _confirm(depD["id"], "mov:b")
        assert rd.status_code == 200, rd.text
        assert _bal(CLI_ID, "USDT") == 200.0, \
            "dos transferencias reales distintas se acreditan ambas"
        # Pero repetir el MISMO movimiento en un tercer depósito → 409.
        depE = _mk_deposit(f"dep_{MARK}_E", tx_hash=h)
        re = _confirm(depE["id"], "mov:a")
        assert re.status_code == 409, re.text
        assert _bal(CLI_ID, "USDT") == 200.0


class TestCICoverage:
    def test_makefile_critical_includes_iter306(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter306_verificacion_dr02_residual.py" in target
