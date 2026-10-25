"""EC01 — regresión: un reintento tras fallo parcial NUNCA duplica el traslado.

Ejecuta la función REAL `issue_or_return_cash` contra la base de datos real,
inyectando fallos en el guardado del evento / autoridad de gasto, y verifica
que la clave de operación produce UN solo traslado y UN solo evento coherente.
"""
import asyncio

from dotenv import load_dotenv

load_dotenv()

import services.courier_cash as cc  # noqa: E402
import services.company_fund_budget as fund_budget  # noqa: E402
from fastapi import HTTPException  # noqa: E402

db = cc.db
ACCT = "facc_ec01_test"
COURIER = "courier_ec01_test"
CODE = "CUP"


async def _reset():
    await db.fund_accounts.delete_many(
        {"courier_custody_id": {"$in": ["ec01_src_test", COURIER]}})
    await db.fund_accounts.delete_many({"id": ACCT})
    await db.fund_account_transfers.delete_many(
        {"courier_id": COURIER})
    await db.courier_cash_events.delete_many({"courier_id": COURIER})
    await db.company_fund_adjustments.delete_many({"id": "adj_ec01_test"})


async def _setup(balance=100000.0):
    await _reset()
    # `courier_custody_id` ficticio: ocupa un slot único propio del índice
    # (courier_custody_id, currency) sin chocar con cuentas reales; no es la
    # custodia del mensajero de prueba (id distinto), solo la caja de origen.
    await db.fund_accounts.insert_one({
        "id": ACCT, "name": "Caja EC01 Test", "currency": CODE,
        "method": "cash", "is_active": True, "created_at": "2026-01-01T00:00:00Z",
        "courier_custody_id": "ec01_src_test",
    })
    await db.company_fund_adjustments.insert_one({
        "id": "adj_ec01_test", "currency": CODE, "account_id": ACCT,
        "amount": balance, "adjustment_type": "inflow",
        "created_at": "2026-01-01T00:00:00Z",
    })


async def _transfers():
    return await db.fund_account_transfers.find(
        {"courier_id": COURIER}, {"_id": 0}).to_list(100)


async def _confirmed_sum():
    rows = await db.fund_account_transfers.find(
        {"courier_id": COURIER, "status": "confirmed"}, {"_id": 0}).to_list(100)
    return round(sum(float(r["amount"]) for r in rows), 2), len(rows)


async def _events():
    return await db.courier_cash_events.find(
        {"courier_id": COURIER}, {"_id": 0}).to_list(100)


def _issue(op_key, amount=20000.0):
    return cc.issue_or_return_cash(
        courier_id=COURIER, courier_name="Mensajero EC01", kind="issued",
        currency=CODE, amount=amount, account_id=ACCT,
        actor_id="admin_test", actor_name="Admin Test", op_key=op_key)


def _return(op_key, amount):
    return cc.issue_or_return_cash(
        courier_id=COURIER, courier_name="Mensajero EC01", kind="returned",
        currency=CODE, amount=amount, account_id=ACCT,
        actor_id="admin_test", actor_name="Admin Test", op_key=op_key)


async def test_event_failure_then_retry():
    """EC01 núcleo: transferencia+espejo OK, evento falla, reintento con la
    MISMA clave → UN traslado (20.000, no 40.000) y UN evento (20.000)."""
    await _setup()
    orig = cc.record_cash_event
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fallo inyectado al guardar el evento")
        return await orig(*a, **k)

    cc.record_cash_event = flaky
    try:
        raised = False
        try:
            await _issue("EC01-EVENTFAIL")
        except Exception as e:  # noqa: BLE001
            raised = True
            print("  1er intento lanzó:", type(e).__name__)
        assert raised, "el 1er intento debió fallar al guardar el evento"
        total, n = await _confirmed_sum()
        evs = await _events()
        assert n == 1 and total == 20000.0, f"tras fallo: {n} transf, {total}"
        assert len(evs) == 0, f"no debía haber evento aún: {len(evs)}"

        # Reintento con la MISMA clave (evento ya no falla).
        res = await _issue("EC01-EVENTFAIL")
        total, n = await _confirmed_sum()
        evs = await _events()
        assert n == 1, f"EC01: se duplicó el traslado → {n} transferencias"
        assert total == 20000.0, f"EC01: total trasladado {total} != 20000"
        assert len(evs) == 1, f"EC01: {len(evs)} eventos (debe ser 1)"
        assert evs[0]["amount"] == 20000.0
        assert res["transfer"]["status"] == "confirmed"
        print("PASS test_event_failure_then_retry → 1 transf 20000, 1 evento 20000")
    finally:
        cc.record_cash_event = orig


async def test_abort_then_retry():
    """Fallo ANTES de mover dinero (autoridad de gasto perdida → aborted) y
    reintento con la misma clave → revive el MISMO traslado, no crea otro."""
    await _setup()
    orig = fund_budget.assert_spend_authority
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # pierde el turno → se aborta el traslado
        return await orig(*a, **k)

    fund_budget.assert_spend_authority = flaky
    try:
        try:
            await _issue("EC01-ABORT")
        except HTTPException as e:
            print("  1er intento 409:", e.detail[:40])
        all_tr = await _transfers()
        assert len(all_tr) == 1 and all_tr[0]["status"] == "aborted", \
            f"debía quedar 1 traslado abortado: {all_tr}"

        res = await _issue("EC01-ABORT")
        all_tr = await _transfers()
        total, n = await _confirmed_sum()
        evs = await _events()
        assert len(all_tr) == 1, f"revive el mismo doc, no crea otro: {len(all_tr)}"
        assert n == 1 and total == 20000.0, f"{n} confirmados, total {total}"
        assert len(evs) == 1, f"{len(evs)} eventos"
        assert res["transfer"]["status"] == "confirmed"
        print("PASS test_abort_then_retry → revive mismo traslado (1), 1 evento")
    finally:
        fund_budget.assert_spend_authority = orig


async def test_concurrent_same_key():
    """Dos ejecuciones concurrentes de la MISMA clave → 1 traslado y 1 evento."""
    await _setup()
    r = await asyncio.gather(
        _issue("EC01-CONCURRENT"), _issue("EC01-CONCURRENT"),
        return_exceptions=True)
    print("  resultados concurrentes:",
          [type(x).__name__ if isinstance(x, Exception) else "ok" for x in r])
    total, n = await _confirmed_sum()
    evs = await _events()
    assert n == 1, f"concurrencia duplicó el traslado → {n}"
    assert total == 20000.0, f"total {total} != 20000"
    assert len(evs) == 1, f"{len(evs)} eventos (debe ser 1)"
    print("PASS test_concurrent_same_key → 1 transf 20000, 1 evento")


async def test_key_reuse_different_params_rejected():
    """Reutilizar la clave con importe distinto → rechazo (no segundo traslado)."""
    await _setup()
    await _issue("EC01-REUSE", amount=20000.0)
    rejected = False
    try:
        await _issue("EC01-REUSE", amount=30000.0)
    except HTTPException as e:
        rejected = e.status_code == 409
        print("  rechazo esperado:", e.status_code, e.detail[:40])
    assert rejected, "debió rechazar la reutilización con importe distinto"
    total, n = await _confirmed_sum()
    assert n == 1 and total == 20000.0, f"{n} confirmados, total {total}"
    print("PASS test_key_reuse_different_params_rejected")


async def test_ec02_concurrent_returns_no_overdraw():
    """EC02: pendiente 20.000; dos rendiciones de 15.000 con claves DISTINTAS
    concurrentes. Solo una debe aprobarse: no se puede rendir 30.000 de 20.000."""
    await _setup()
    # El mensajero recibe 20.000 (quedan por rendir).
    await _issue("EC02-SEED-ISSUE", amount=20000.0)
    held0 = await cc.courier_held_cash(COURIER, CODE)
    assert held0 == 20000.0, f"pendiente inicial {held0} != 20000"

    r = await asyncio.gather(
        _return("EC02-RET-A", 15000.0), _return("EC02-RET-B", 15000.0),
        return_exceptions=True)
    oks = [x for x in r if not isinstance(x, Exception)]
    errs = [x for x in r if isinstance(x, Exception)]
    print("  rendiciones:", "ok=%d err=%d" % (len(oks), len(errs)),
          [getattr(e, "detail", type(e).__name__)[:30] for e in errs])

    ret_tr = await db.fund_account_transfers.find(
        {"courier_id": COURIER, "courier_cash_kind": "returned",
         "status": "confirmed"}, {"_id": 0}).to_list(100)
    ret_total = round(sum(float(t["amount"]) for t in ret_tr), 2)
    held_final = await cc.courier_held_cash(COURIER, CODE)
    assert len(oks) == 1 and len(errs) == 1, \
        f"EC02: debía aprobarse 1 y rechazarse 1 (ok={len(oks)}, err={len(errs)})"
    assert ret_total == 15000.0, f"EC02: se rindió {ret_total}, no 15000"
    assert held_final == 5000.0, f"EC02: pendiente final {held_final} != 5000"
    print("PASS test_ec02_concurrent_returns_no_overdraw → 1 rendición 15000, "
          "pendiente 5000")


async def test_ec02_return_blocked_when_transfer_confirmed_event_pending():
    """EC02 (ventana de evento): una rendición confirmada SIN evento aún debe
    reducir el disponible para una segunda rendición distinta."""
    await _setup()
    await _issue("EC02-SEED2", amount=20000.0)
    orig = cc.record_cash_event
    calls = {"n": 0}

    async def flaky(*a, **k):
        # Falla SOLO el evento de la primera rendición: deja el traslado
        # confirmado sin evento (ventana EC02).
        if k.get("kind") == "returned" and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("fallo inyectado al guardar evento de rendición")
        return await orig(*a, **k)

    cc.record_cash_event = flaky
    try:
        try:
            await _return("EC02-WINDOW-A", 15000.0)
        except Exception as e:  # noqa: BLE001
            print("  1ra rendición falló su evento:", type(e).__name__)
        # Traslado confirmado, evento ausente → disponible real = 5.000.
        held = await cc.courier_held_cash(COURIER, CODE)
        assert held == 5000.0, f"disponible con evento pendiente {held} != 5000"
        # Segunda rendición de 15.000 debe RECHAZARSE (solo quedan 5.000).
        rejected = False
        try:
            await _return("EC02-WINDOW-B", 15000.0)
        except HTTPException as e:
            rejected = e.status_code == 400
            print("  2da rendición rechazada:", e.status_code, e.detail[:40])
        assert rejected, "EC02: la 2da rendición debió rechazarse (evento en vuelo)"
    finally:
        cc.record_cash_event = orig
    print("PASS test_ec02_return_blocked_when_transfer_confirmed_event_pending")


async def main():
    try:
        await test_event_failure_then_retry()
        await test_abort_then_retry()
        await test_concurrent_same_key()
        await test_key_reuse_different_params_rejected()
        await test_ec02_concurrent_returns_no_overdraw()
        await test_ec02_return_blocked_when_transfer_confirmed_event_pending()
        print("\nALL EC01/EC02 TESTS PASSED")
    finally:
        await _reset()


if __name__ == "__main__":
    asyncio.run(main())
