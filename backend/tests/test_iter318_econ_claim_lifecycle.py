"""iter318 — CB10 v4 (MEDIA): la reserva de identidad económica quedaba RETENIDA
tras revertir una conciliación y borrar la importación.

Informe reproducido (con las rutas originales):
  1) Conciliar automáticamente A: crédito de 100 y reserva económica de btx-A.
  2) Revertir la conciliación (rollback): 200, saldo vuelve a 0.
  3) Borrar la importación: 200, se elimina su movimiento bancario.
  4) Reimportar el MISMO pago con import y movimiento nuevos.
  El motor encuentra una orden compatible, pero la reserva seguía perteneciendo a
  btx-A (un registro que ya no existe) → el pago caía a REVISIÓN y el saldo
  permanecía en 0.

Fix (v4): el ciclo de vida de la reserva económica se integra con la reversión y
el borrado posterior. El rollback la libera SOLO tras revertir todos los efectos
del crédito (orden a pendiente / acumulado debitado, vínculo bancario liberado).
El borrado de importación libera las reservas de SUS movimientos (ya sin crédito
vivo). Propiedad ESTRICTA por `tx_id`: una reversión/borrado antiguo jamás libera
una reserva nueva de otra reimportación.

CIERRE: tras revertir y borrar A, la reimportación legítima reserva su identidad
y acredita UNA vez; mientras el crédito anterior siga vigente, sigue bloqueada.

Infra basada en iter315 (in-process con `require_permission` stubbeado y `_run`
que reinicia el loop de Motor).
"""
import asyncio
import os
import types
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

from conftest import BASE_URL  # noqa: F401 — asegura el servidor arriba

UID = "user_test_cli318"
MARK = "iter318"
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
    db.bank_statement_imports.delete_many({"id": {"$regex": f"^imp_{MARK}"}})
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


def _mk_import(suffix):
    iid = f"imp_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().bank_statement_imports.insert_one({
        "id": iid, "processing_status": "processed", "currency": "USD",
        "bank_name": "Banco Prueba", "bank_account_id": None,
        "original_file_name": "extracto.pdf", "stored_file_url": "",
        "created_at": _now(), "updated_at": _now()})
    return iid


def _mk_tx(suffix, import_id, amount=100.0, status="unmatched",
           sender="Persona Prueba"):
    """Movimiento bancario con identidad económica estable (mismo remitente,
    importe, cuenta, moneda, fecha) — las reimportaciones comparten identidad."""
    tid = f"tx_{MARK}_{suffix}_{uuid.uuid4().hex[:6]}"
    _db().bank_transactions.insert_one({
        "id": tid, "status": status, "direction": "credit",
        "amount": float(amount), "currency": "USD", "candidates": [],
        "bank_account_id": None, "sender_name": sender,
        "description": f"Transferencia {sender}",
        "transaction_date": _today(),
        "statement_import_id": import_id,
        "fingerprint": f"fp_{uuid.uuid4().hex}",
        "fingerprint_original": f"fpo_{suffix}_{uuid.uuid4().hex[:8]}",
        "created_at": _now(), "updated_at": _now()})
    return tid


def _econ_key_for(tx_id):
    import services.reconciliation_matcher as rm
    return rm._economic_identity_key(
        _db().bank_transactions.find_one({"id": tx_id}, {"_id": 0}))


async def _automatch(tx_id):
    import services.reconciliation_matcher as rm
    tx_doc = await rm.db.bank_transactions.find_one({"id": tx_id}, {"_id": 0})
    return await rm.run_matching(
        {"currency": "USD", "bank_account_id": None}, [tx_doc])


async def _rollback(tx_id, reason="reversion valida de prueba"):
    import routes.reconciliation as recon
    from fastapi import HTTPException
    orig = recon.require_permission
    recon.require_permission = _stub_permission
    req = types.SimpleNamespace(client=None)
    try:
        await recon.rollback_match(
            tx_id, types.SimpleNamespace(reason=reason), req)
        return 200
    except HTTPException as ex:
        return ex.status_code
    finally:
        recon.require_permission = orig


async def _delete_import(import_id):
    import routes.reconciliation as recon
    from fastapi import HTTPException
    orig = recon.require_permission
    recon.require_permission = _stub_permission
    req = types.SimpleNamespace(client=None)
    try:
        await recon.delete_import(import_id, req)
        return 200
    except HTTPException as ex:
        return ex.status_code
    finally:
        recon.require_permission = orig


class TestEconClaimLifecycle:
    def setup_method(self, _):
        _cleanup()
        _db().users.update_one({"user_id": UID},
                               {"$set": {"vip_balances": {}}})

    def teardown_method(self, _):
        _cleanup()

    def test_rollback_releases_claim_and_reimport_credits_once(self):
        """Reproductor completo del informe: conciliar → revertir → reimportar.
        Tras el rollback la reserva económica queda liberada, así que la
        reimportación legítima del mismo pago acredita UNA vez (saldo 100,
        nunca atascada en revisión con saldo 0)."""
        order_a = _mk_order("A")
        imp1 = _mk_import("1")
        tx_a = _mk_tx("A", imp1)
        econ_key = _econ_key_for(tx_a)
        db = _db()

        # 1) Conciliación automática: crédito de 100 + reserva económica de tx_a.
        counts1 = _run(lambda: _automatch(tx_a))
        assert counts1.get("auto") == 1, counts1
        assert _bal("USDT") == 100.0
        claim = db.economic_credit_claims.find_one({"_id": econ_key})
        assert claim and claim.get("tx_id") == tx_a, "la reserva la posee tx_a"
        assert db.orders.find_one({"id": order_a})["status"] == "approved"

        # 2) Rollback: revierte todos los efectos del crédito y LIBERA la reserva.
        code = _run(lambda: _rollback(tx_a))
        assert code == 200, f"rollback válido: {code}"
        assert _bal("USDT") == 0.0, "el saldo vuelve a 0"
        assert db.orders.find_one({"id": order_a})["status"] == "pending"
        assert db.economic_credit_claims.find_one({"_id": econ_key}) is None, \
            "la reserva económica se libera al revertir por completo"

        # 3) Reimportar el MISMO pago (import + movimiento nuevos) → acredita 1 vez.
        imp2 = _mk_import("2")
        tx_c = _mk_tx("C", imp2)
        counts2 = _run(lambda: _automatch(tx_c))
        assert counts2.get("auto") == 1, \
            f"la reimportación legítima concilia, no cae a revisión: {counts2}"
        assert _bal("USDT") == 100.0, "crédito único tras la reimportación"
        claim2 = db.economic_credit_claims.find_one({"_id": econ_key})
        assert claim2 and claim2.get("tx_id") == tx_c, \
            "la reserva nueva la posee ahora tx_c"

    def test_delete_import_releases_claim_scoped_to_that_import(self):
        """El borrado de una importación libera las reservas de SUS movimientos
        (ya revertidos, sin crédito vivo), pero NO toca la reserva de otra
        importación — propiedad estricta por tx_id."""
        db = _db()
        imp1, imp2 = _mk_import("D1"), _mk_import("D2")
        # Movimientos revertidos (unmatched, sin crédito vivo) con reserva colgada
        # —como dejaría un rollback anterior a este fix.
        tx1 = _mk_tx("D1", imp1, sender="Remitente Uno")
        tx2 = _mk_tx("D2", imp2, amount=150.0, sender="Remitente Dos")
        k1, k2 = _econ_key_for(tx1), _econ_key_for(tx2)
        db.economic_credit_claims.insert_one({"_id": k1, "tx_id": tx1,
                                              "at": _now()})
        db.economic_credit_claims.insert_one({"_id": k2, "tx_id": tx2,
                                              "at": _now()})

        code = _run(lambda: _delete_import(imp1))
        assert code == 200, f"borrado válido: {code}"
        assert db.bank_statement_imports.find_one({"id": imp1}) is None
        assert db.bank_transactions.find_one({"id": tx1}) is None
        assert db.economic_credit_claims.find_one({"_id": k1}) is None, \
            "se libera la reserva del movimiento borrado"
        # La reserva de la OTRA importación permanece intacta.
        assert db.economic_credit_claims.find_one({"_id": k2}) is not None, \
            "propiedad estricta: no se toca la reserva de otro extracto"

    def test_delete_import_blocked_while_credit_live_keeps_claim(self):
        """Mientras el crédito siga vigente (movimiento conciliado), el borrado
        se BLOQUEA (409) y la reserva se conserva: no se orfana ni se libera un
        cobro vivo."""
        db = _db()
        _mk_order("LIVE")
        imp = _mk_import("LIVE")
        tx = _mk_tx("LIVE", imp)
        econ_key = _econ_key_for(tx)

        counts = _run(lambda: _automatch(tx))
        assert counts.get("auto") == 1, counts
        assert db.economic_credit_claims.find_one({"_id": econ_key}) is not None

        code = _run(lambda: _delete_import(imp))
        assert code == 409, "no se puede borrar un extracto con crédito vivo"
        assert db.bank_statement_imports.find_one({"id": imp}) is not None
        assert db.economic_credit_claims.find_one({"_id": econ_key}) is not None, \
            "mientras el crédito esté vivo la reserva sigue bloqueando"

    def test_strict_ownership_old_release_keeps_new_reservation(self):
        """`release_economic_identity` solo libera si ESTE tx la posee: una
        reversión antigua (tx_A) jamás libera una reserva nueva (tx_C)."""
        import services.reconciliation_matcher as rm
        db = _db()
        key = f"econ|iter318strict|{uuid.uuid4().hex[:8]}"
        db.economic_credit_claims.insert_one(
            {"_id": key, "tx_id": f"tx_{MARK}_C", "at": _now()})

        # La reversión antigua de otro dueño no libera la reserva.
        _run(lambda: rm.release_economic_identity(key, f"tx_{MARK}_A"))
        assert db.economic_credit_claims.find_one({"_id": key}) is not None, \
            "una reversión antigua no libera una reserva de otro movimiento"

        # El dueño real sí la libera.
        _run(lambda: rm.release_economic_identity(key, f"tx_{MARK}_C"))
        assert db.economic_credit_claims.find_one({"_id": key}) is None
