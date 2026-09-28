"""iter305 — Verificación de Depósitos y Retiros (informe 91b879e):
los dos riesgos concurrentes que quedaban abiertos.

DR02 v3 (alta)   Dos confirmaciones VIVAS del MISMO depósito con movimientos
                 distintos ya no separan la reserva del movimiento confirmado.
                 La identidad reservada se graba en el propio depósito
                 (`evidence_claim_movement`) y la confirmación final SOLO gana
                 si ese movimiento sigue vigente: la petición anterior recibe
                 409 y jamás libera un movimiento que otra pueda consumir. El
                 depósito y su reserva terminan con la MISMA identidad y un
                 segundo depósito no consume el movimiento ya confirmado.

DR09 v3 (crítica) El reembolso administrativo ASEGURA la protección de la
                 entrega ANTES de mover dinero: tras reservar la intención la
                 COMPROMETE de inmediato (no robable ni liberable por un
                 perdedor con lectura obsoleta). Si un robo+liberación en la
                 ventana previa dejó la entrega sellada, `commit` lo detecta y
                 el rechazo NO acredita reembolso (entrega válida sin
                 reembolso). Jamás entrega sellada Y reembolso a la vez.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api"
MARK = "iter305"

CLIA_ID = "user_test_cli305a"
CLIA_TOKEN = f"test_session_{uuid.uuid4().hex}"
COURIER_ID = "user_test_cou305"
COURIER_TOKEN = f"test_session_{uuid.uuid4().hex}"


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


def _old(minutes=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


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
    for uid, tok, extra in (
        (CLIA_ID, CLIA_TOKEN, {"role": "vip"}),
        (COURIER_ID, COURIER_TOKEN, {"role": "vip", "is_courier": True}),
    ):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "email": f"{uid}@test.com", "name": uid,
                      "vip_balances": {}, "applied_credit_ops": [], **extra}},
            upsert=True)
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid,
                      "expires_at": "2099-01-01T00:00:00+00:00"}},
            upsert=True)
    db.currencies.update_one(
        {"code": "USDT"},
        {"$setOnInsert": {"code": "USDT", "name": "Tether", "type": "crypto",
                          "is_active": True, "delivery_methods": ["crypto"]}},
        upsert=True)
    _cleanup_data()


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [CLIA_ID, COURIER_ID]}})
    db.user_sessions.delete_many({"session_token": {
        "$in": [CLIA_TOKEN, COURIER_TOKEN]}})
    _cleanup_data()


def _cleanup_data():
    db = _db()
    db.withdrawals.delete_many({"user_id": CLIA_ID})
    db.deposits.delete_many({"user_id": CLIA_ID})
    db.deposits.delete_many({"tx_hash": {"$regex": MARK}})
    db.deliveries.delete_many({"id": {"$regex": f"^dv_{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})


def _mk_deposit(dep_id, amount=100.0, currency="USDT", tx_hash=None,
                network="BEP20", status="pending"):
    doc = {
        "id": dep_id, "user_id": CLIA_ID, "user_email": f"{CLIA_ID}@test.com",
        "user_name": CLIA_ID, "user_role": "vip", "currency": currency,
        "amount": float(amount), "method": "crypto", "cash_mode": None,
        "network": network, "usdt_equivalent": None, "account_holder": None,
        "tx_hash": tx_hash, "proof_url": None, "note": None, "status": status,
        "admin_note": None, "reviewed_at": None, "reviewed_by": None,
        "created_at": _now(), "updated_at": _now(),
    }
    _db().deposits.insert_one(dict(doc))
    return doc


def _mk_withdrawal(wid, amount=100.0, currency="USD", method="cash",
                   status="approved"):
    doc = {
        "id": wid, "user_id": CLIA_ID, "user_email": f"{CLIA_ID}@test.com",
        "user_name": CLIA_ID, "amount_usd": float(amount), "currency": currency,
        "method": method, "details": "detalle prueba", "status": status,
        "created_at": _now(), "updated_at": _now(),
    }
    _db().withdrawals.insert_one(dict(doc))
    return doc


def _mk_delivery(dvid, wid, status="arrived", **extra):
    doc = {
        "id": dvid, "kind": "withdrawal", "ref_id": wid, "status": status,
        "courier_id": COURIER_ID, "courier_name": COURIER_ID,
        "user_id": CLIA_ID, "client_name": "Cliente Prueba",
        "amount_label": "100 USD", "timeline": [], "payout_credited": False,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deliveries.insert_one(dict(doc))
    return doc


def _confirm(dep_id, body=None):
    return requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                         headers=_h(ADMIN), json=body or {})


def _cancel(wid):
    return requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                         headers=_h(CLIA_TOKEN))


def _seal_delivered(dvid):
    return requests.post(f"{API}/courier/deliveries/{dvid}/status",
                         headers=_h(COURIER_TOKEN), json={"status": "delivered"})


# ---------------------------------------------------------------------------
# Proxy de base de datos para inyectar una barrera de concurrencia SOLO en
# `deposits.update_one` (las colecciones motor no se cachean, así que se
# reemplaza el `db` del módulo por un envoltorio durante la prueba).
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


# ---------------------------------------------------------------------------
# DR02 v3 — confirmaciones concurrentes del mismo depósito con movimientos
# distintos: reserva y confirmación quedan vinculadas de forma indivisible.
# ---------------------------------------------------------------------------
class TestDR02ConcurrentConfirm:
    def test_evidence_move_during_live_confirmation_no_double_credit(self):
        """Reproducción evidence_move_during_live_confirmation: la primera
        confirmación reserva log:0 y queda pausada antes de sellar; una
        segunda confirmación VIVA del mismo depósito mueve la reserva a log:1.
        Al reanudar, la primera (log:0) recibe 409 y la segunda (log:1)
        confirma — el depósito y su reserva terminan con la MISMA identidad
        (log:1). Un segundo depósito con log:0 se acredita como movimiento
        realmente distinto, jamás como el que ya confirmó el primero."""
        h = f"{MARK}hash_conc"
        depA = _mk_deposit(f"dep_{MARK}_c1", tx_hash=h)
        _set_bal(CLIA_ID, "USDT", 0)

        async def race():
            import routes.deposits as dep
            real_db = dep.db
            staff = await real_db.users.find_one({"user_id": "user_test_admin01"},
                                                 {"_id": 0})
            if not staff:
                staff = {"user_id": "user_test_admin01", "role": "admin",
                         "email": "admin.test@resilience.com"}
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
                await asyncio.wait_for(reached["log:0"].wait(), 15)   # reservó log:0, pausa en sello
                dA2 = await real_db.deposits.find_one({"id": depA["id"]},
                                                      {"_id": 0})
                t1 = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dA2), staff, "log:1"))
                await asyncio.wait_for(reached["log:1"].wait(), 15)   # movió reserva→log:1, pausa
                gates["log:0"].set()
                r0 = (await asyncio.gather(t0, return_exceptions=True))[0]
                gates["log:1"].set()
                r1 = (await asyncio.gather(t1, return_exceptions=True))[0]
                return r0, r1
            finally:
                dep.db = real_db

        r0, r1 = _run(race)
        from fastapi import HTTPException
        assert isinstance(r0, HTTPException) and r0.status_code == 409, r0
        assert isinstance(r1, dict), r1
        fresh = _db().deposits.find_one({"id": depA["id"]})
        assert fresh["status"] == "confirmed"
        assert fresh["evidence_movement_id"] == "log:1", \
            "el depósito confirma con la identidad realmente vigente"
        claim = _db().crypto_evidence_claims.find_one({"deposit_id": depA["id"]})
        assert claim["movement_id"] == "log:1", \
            "reserva y confirmación quedan con la MISMA identidad"
        assert _bal(CLIA_ID, "USDT") == 100.0, "un solo abono para el depósito"
        # Un segundo depósito con log:0 es un movimiento realmente distinto:
        # se acredita, pero jamás consume el log:1 que A confirmó.
        depB = _mk_deposit(f"dep_{MARK}_c2", tx_hash=h)
        rb = _confirm(depB["id"], {"evidence_movement_id": "log:0"})
        assert rb.status_code == 200, rb.text
        fb = _db().deposits.find_one({"id": depB["id"]})
        assert fb["evidence_movement_id"] == "log:0"
        assert fb["evidence_movement_id"] != fresh["evidence_movement_id"], \
            "B no consume el movimiento que A confirmó"
        assert _bal(CLIA_ID, "USDT") == 200.0

    def test_same_movement_second_deposit_still_blocked(self):
        """Regresión: si un segundo depósito intenta el MISMO movimiento ya
        confirmado por otro, recibe 409 (identidad de un solo uso)."""
        h = f"{MARK}hash_same"
        depA = _mk_deposit(f"dep_{MARK}_s1", tx_hash=h)
        depB = _mk_deposit(f"dep_{MARK}_s2", tx_hash=h)
        _set_bal(CLIA_ID, "USDT", 0)
        ra = _confirm(depA["id"], {"evidence_movement_id": "mov:9"})
        assert ra.status_code == 200, ra.text
        rb = _confirm(depB["id"], {"evidence_movement_id": "mov:9"})
        assert rb.status_code == 409, rb.text
        assert _bal(CLIA_ID, "USDT") == 100.0


# ---------------------------------------------------------------------------
# DR09 v3 — la protección de la entrega se asegura ANTES de mover dinero.
# ---------------------------------------------------------------------------
class TestDR09CommitStrict:
    def test_commit_returns_false_when_delivery_already_sealed(self):
        """`commit_origin_cancel_intent` devuelve False si la entrega ya se
        selló: la protección es imposible y el reembolso debe rechazarse."""
        wid = f"wd_{MARK}_seal"
        _mk_withdrawal(wid)
        dv = _mk_delivery(f"dv_{MARK}_seal", wid, status="delivered",
                          pin_verified=True)

        async def call():
            from services.deliveries import commit_origin_cancel_intent
            return await commit_origin_cancel_intent(dv["id"], "staff")

        assert _run(call) is False

    def test_commit_secures_active_delivery(self):
        """Sobre una entrega activa, `commit` deja la intención comprometida y
        devuelve True — el sello del mensajero queda impedido."""
        wid = f"wd_{MARK}_active"
        _mk_withdrawal(wid)
        dv = _mk_delivery(f"dv_{MARK}_active", wid, status="arrived")

        async def call():
            from services.deliveries import commit_origin_cancel_intent
            ok = await commit_origin_cancel_intent(dv["id"], "staff")
            return ok

        assert _run(call) is True
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        assert (fresh.get("origin_cancel_intent") or {}).get("committed") is True

    def test_force_release_only_removes_own_token(self):
        """`force_release_origin_cancel_intent` solo retira la intención de su
        propio token; jamás toca la de otra decisión."""
        wid = f"wd_{MARK}_frel"
        _mk_withdrawal(wid)
        dv = _mk_delivery(
            f"dv_{MARK}_frel", wid, status="arrived",
            origin_cancel_intent={"at": _now(), "by": "staff",
                                  "token": "tok_owner", "committed": True})

        async def call():
            from services.deliveries import force_release_origin_cancel_intent
            await force_release_origin_cancel_intent(dv["id"], "tok_other")
            mid = _db().deliveries.find_one(
                {"id": dv["id"]}).get("origin_cancel_intent")
            await force_release_origin_cancel_intent(dv["id"], "tok_owner")
            return mid

        mid = _run(call)
        assert mid and mid.get("token") == "tok_owner", \
            "un token ajeno no retira la protección"
        gone = _db().deliveries.find_one({"id": dv["id"]})
        assert "origin_cancel_intent" not in gone, \
            "el token propio sí la retira al abandonar"


class TestDR09StaleReleaseNeverBoth:
    def test_stale_release_after_admin_refund_never_delivers_and_refunds(self):
        """Reproducción cancellation_release_after_stale_origin_read: el
        rechazo administrativo reserva la intención y (con el fix) la
        COMPROMETE antes de persistir el reembolso. Aun si en la ventana
        previa una cancelación de cliente perdedora roba y libera la intención
        vencida y el mensajero sella la entrega, el `commit` detecta la entrega
        sellada y el rechazo NO acredita reembolso. Resultado: entrega válida
        SIN reembolso — jamás ambos."""
        wid = f"wd_{MARK}_stale"
        dvid = f"dv_{MARK}_stale"
        _mk_withdrawal(wid, status="approved")   # aprobado: el cliente no puede cancelar
        _mk_delivery(dvid, wid, status="arrived")  # sin PIN → sello sin PIN
        _set_bal(CLIA_ID, "USD", 0)

        async def race():
            import services.deliveries as sd
            import routes.admin_withdrawals as aw
            orig_commit = sd.commit_origin_cancel_intent
            commit_reached = asyncio.Event()
            commit_gate = asyncio.Event()

            async def held_commit(job_id, actor_id=""):
                # Pausa a la reserva del admin ENTRE reservar y comprometer,
                # recreando la ventana que explotaba la carrera.
                commit_reached.set()
                await commit_gate.wait()
                return await orig_commit(job_id, actor_id)

            sd.commit_origin_cancel_intent = held_commit
            try:
                w = await sd.db.withdrawals.find_one({"id": wid}, {"_id": 0})
                sets = {"status": "rejected", "rejected_at": _now(),
                        "admin_note": ""}
                admin_task = asyncio.create_task(
                    aw._claim_entering_rejected(
                        w, sets, "USD", 100.0, "user_test_admin01"))
                await asyncio.wait_for(commit_reached.wait(), 15)
                # La reserva del admin ya existe (sin comprometer). Se envejece
                # a >120s para que la cancelación del cliente la considere
                # vencida (equivale a que el request del admin se estancó).
                _db().deliveries.update_one(
                    {"id": dvid},
                    {"$set": {"origin_cancel_intent.at": _old(3)}})
                loop = asyncio.get_event_loop()
                cr = await loop.run_in_executor(None, lambda: _cancel(wid))
                dr = await loop.run_in_executor(None, lambda: _seal_delivered(dvid))
                commit_gate.set()
                admin_res = (await asyncio.gather(
                    admin_task, return_exceptions=True))[0]
                return cr.status_code, dr.status_code, admin_res
            finally:
                sd.commit_origin_cancel_intent = orig_commit

        cancel_code, seal_code, admin_res = _run(race)
        from fastapi import HTTPException
        # El cliente pierde (retiro aprobado, no pendiente) y el mensajero
        # logra sellar en la ventana; pero el reembolso se rechaza.
        assert cancel_code == 409, cancel_code
        assert seal_code == 200, seal_code
        assert isinstance(admin_res, HTTPException) \
            and admin_res.status_code == 409, admin_res
        wd = _db().withdrawals.find_one({"id": wid})
        dv = _db().deliveries.find_one({"id": dvid})
        assert dv["status"] == "delivered", "la entrega quedó sellada"
        assert wd["status"] != "rejected", "el retiro NO se rechazó"
        assert not wd.get("balance_refunded"), "sin reembolso"
        assert _bal(CLIA_ID, "USD") == 0.0, \
            "jamás entrega sellada Y reembolso a la vez"

    def test_admin_reject_while_courier_pending_refunds_and_blocks_seal(self):
        """Caso normal (sin estancamiento): el admin rechaza mientras la
        entrega sigue activa. La intención se compromete al instante, el
        reembolso se acredita UNA vez y un sello tardío del mensajero recibe
        409 — reembolso único con entrega impedida."""
        wid = f"wd_{MARK}_normal"
        dvid = f"dv_{MARK}_normal"
        _mk_withdrawal(wid, status="approved")
        _mk_delivery(dvid, wid, status="arrived")
        _set_bal(CLIA_ID, "USD", 0)

        async def do_reject():
            import routes.admin_withdrawals as aw
            from db_client import db
            w = await db.withdrawals.find_one({"id": wid}, {"_id": 0})
            sets = {"status": "rejected", "rejected_at": _now(),
                    "admin_note": ""}
            await aw._claim_entering_rejected(w, sets, "USD", 100.0,
                                              "user_test_admin01")
            from services.deliveries import handle_origin_rejected
            await handle_origin_rejected("withdrawal", wid,
                                         actor_id="user_test_admin01",
                                         note="retiro rechazado")

        _run(do_reject)
        assert _bal(CLIA_ID, "USD") == 100.0, "reembolso único"
        wd = _db().withdrawals.find_one({"id": wid})
        assert wd["status"] == "rejected" and wd.get("balance_refunded")
        # El mensajero ya no puede sellar (entrega cancelada por el rechazo).
        r = _seal_delivered(dvid)
        assert r.status_code == 409, r.text
        dv = _db().deliveries.find_one({"id": dvid})
        assert dv["status"] != "delivered"


# ---------------------------------------------------------------------------
# CI — la suite queda en el conjunto crítico
# ---------------------------------------------------------------------------
class TestCICoverage:
    def test_makefile_critical_includes_iter305(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter305_verificacion_dr91b879e.py" in target
