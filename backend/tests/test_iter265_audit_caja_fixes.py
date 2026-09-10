"""iter265 — Correcciones de la Auditoría 7 (Caja de efectivo y fondo, H01–H07).

H01 la caja física y la cuenta contable cuentan la misma historia: retiros de
    empresa pagados desde la cuenta de caja y transferencias internas que
    tocan la caja se reflejan como movimientos físicos (idempotente, con
    desglose pendiente visible); los movimientos directos en la caja del
    sistema quedan marcados «sin contrapartida»
H02 los retiros no pagados RESERVAN el fondo (dos de 80 contra 100 no pasan);
    el pago revalida el disponible y las transiciones son atómicas: un
    rechazo obsoleto pierde con conflicto ante un pago que ganó
H03 la caja automática se identifica por `system_purpose`, no por el nombre:
    renombrarla no divide el historial ni crea cajas nuevas
H04 un arqueo temprano deja de valer como cierre si después hay movimientos
H05 claves de denominación equivalentes (100 / "100.0") se consolidan
H06 reporte mensual y Excel iteran por cursor (sin tope de 20.000)
H07 el saldo inicial es inmutable una vez hay operativa (correcciones = movs)
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER265"
CCY = "I265X"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _db()
    db.company_withdrawals.delete_many({"beneficiary": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"source_name": {"$regex": MARK}})
    db.fund_account_transfers.delete_many({"note": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    # V01 — el presupuesto de reservas se reconstruye desde los retiros
    # reales; borrarlo evita residuos de docs eliminados por los tests.
    db.company_fund_budgets.delete_many({})
    ids = [b["id"] for b in db.cash_boxes.find(
        {"name": {"$regex": MARK}, "system_purpose": {"$exists": False}},
        {"_id": 0, "id": 1})]
    if ids:
        db.cash_box_movements.delete_many({"box_id": {"$in": ids}})
        db.cash_box_arqueos.delete_many({"box_id": {"$in": ids}})
        db.cash_boxes.delete_many({"id": {"$in": ids}})
    db.currencies.delete_many({"code": CCY})
    db.fund_accounts.delete_many({"currency": CCY})
    db.fund_account_denoms.delete_many({"note": {"$regex": MARK}})


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


def _adjust(body):
    return requests.post(f"{API}/admin/company-funds/adjustments",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _cw_create(body):
    return requests.post(f"{API}/admin/company-withdrawals",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _cw_status(cwid, body):
    return requests.put(f"{API}/admin/company-withdrawals/{cwid}/status",
                        headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _mk_box(scope="empresa"):
    r = requests.post(f"{API}/cashbox/boxes", headers=_hdr(ADMIN_TOKEN),
                      json={"name": f"{MARK} {uuid.uuid4().hex[:6]}",
                            "scope": scope})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_mov(box_id, amount, denoms=None, fund="CUP", mtype="entrada"):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/movimientos",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"fund": fund, "type": mtype, "amount": amount,
                            "concept": f"mov {MARK}", "denominations": denoms})
    assert r.status_code == 200, r.text
    return r.json()


def _resumen(box_id, fund="CUP"):
    r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                     params={"fund": fund}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _auto_box():
    return _db().cash_boxes.find_one({"system_purpose": "company_cash"},
                                     {"_id": 0})


def _fund_row(code):
    r = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((x for x in r.json() if x["currency"] == code), None)


def _run_backfill():
    async def _f():
        from services.cash_box_sync import backfill_cash_operations
        return await backfill_cash_operations()
    return _run(_f)


def _ensure_usd_available(needed: float):
    """V06 — el entorno de CI puede arrancar con custodia de clientes o
    reservas USD que dejan corto el disponible real: se aporta la diferencia
    por transferencia (no toca la caja física ni el desglose de billetes)."""
    row = _fund_row("USD") or {}
    avail = float(row.get("balance_available") or 0.0)
    reserved = sum(float(r.get("amount") or 0)
                   for r in _db().company_withdrawals.find(
                       {"currency": "USD",
                        "status": {"$in": ["pending", "approved"]}},
                       {"_id": 0, "amount": 1}))
    missing = round(needed - (avail - reserved), 2)
    if missing > 0:
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": missing, "method": "transfer",
                     "source_name": f"{MARK} topup disponible"})
        assert r.status_code == 200, r.text


class TestH02WithdrawalIntegrity:
    def setup_method(self, _):
        _cleanup()
        _db().currencies.update_one(
            {"code": CCY},
            {"$setOnInsert": {"code": CCY, "name": "Moneda Test 265",
                              "type": "fiat", "is_active": True}}, upsert=True)

    def teardown_method(self, _):
        _cleanup()

    def test_pending_withdrawals_reserve_the_fund(self):
        """Repro del auditor: fondo 100 → dos retiros de 80 no se autorizan."""
        r = _adjust({"adjustment_type": "inflow", "currency": CCY,
                     "amount": 100, "method": "transfer",
                     "source_name": f"{MARK} aporte"})
        assert r.status_code == 200, r.text

        a = _cw_create({"currency": CCY, "amount": 80,
                        "beneficiary": f"{MARK} A", "concept": "gasto A"})
        assert a.status_code == 200, a.text
        b = _cw_create({"currency": CCY, "amount": 80,
                        "beneficiary": f"{MARK} B", "concept": "gasto B"})
        assert b.status_code == 400, \
            f"el segundo retiro debe chocar con la reserva: {b.status_code}"
        assert "reservado" in b.json()["detail"].lower(), b.json()

        # pagar A (100 ≥ 80) y verificar que el fondo quedó en 20
        r = _cw_status(a.json()["id"], {"status": "paid"})
        assert r.status_code == 200, r.text
        assert r.json().get("paid_at"), "el pago debe registrar paid_at"
        c = _cw_create({"currency": CCY, "amount": 30,
                        "beneficiary": f"{MARK} C", "concept": "gasto C"})
        assert c.status_code == 400, \
            "con 20 disponibles un retiro de 30 no puede autorizarse"

    def test_transitions_are_atomic_and_final(self):
        _adjust({"adjustment_type": "inflow", "currency": CCY, "amount": 100,
                 "method": "transfer", "source_name": f"{MARK} aporte"})
        a = _cw_create({"currency": CCY, "amount": 50,
                        "beneficiary": f"{MARK} A", "concept": "x"}).json()
        assert _cw_status(a["id"], {"status": "paid"}).status_code == 200
        # H02b — el rechazo tardío pierde con conflicto, el pago no se pisa
        r = _cw_status(a["id"], {"status": "rejected"})
        assert r.status_code == 409, \
            f"rechazar un retiro pagado debe dar conflicto: {r.status_code}"
        db = _db()
        fresh = db.company_withdrawals.find_one({"id": a["id"]}, {"_id": 0})
        assert fresh["status"] == "paid", "el pago nunca se sobrescribe"
        # rejected también es final
        d = _cw_create({"currency": CCY, "amount": 10,
                        "beneficiary": f"{MARK} D", "concept": "x"}).json()
        assert _cw_status(d["id"], {"status": "rejected"}).status_code == 200
        r = _cw_status(d["id"], {"status": "paid"})
        assert r.status_code == 409, "un retiro rechazado no puede pagarse"

    def test_pay_revalidates_available_fund(self):
        """Retiro creado con fondo suficiente, pero el fondo baja antes del
        pago → el pago debe rechazarse explícitamente (409), nunca colarse."""
        _adjust({"adjustment_type": "inflow", "currency": CCY, "amount": 100,
                 "method": "transfer", "source_name": f"{MARK} aporte"})
        a = _cw_create({"currency": CCY, "amount": 80,
                        "beneficiary": f"{MARK} A", "concept": "x"}).json()
        # el fondo se reduce a 30 antes de pagar
        r = _adjust({"adjustment_type": "outflow", "currency": CCY,
                     "amount": 70, "method": "transfer",
                     "source_name": f"{MARK} salida"})
        assert r.status_code == 200, r.text
        r = _cw_status(a["id"], {"status": "paid"})
        assert r.status_code == 409, \
            f"pagar 80 con 30 disponibles debe dar conflicto: {r.status_code}"
        assert "insuficiente" in r.json()["detail"].lower()

    def test_client_custody_reduces_available_fund(self):
        """iter266 — el dinero en custodia de clientes NO financia retiros:
        balance 100 con 30 en custodia → disponible real 70."""
        db = _db()
        _adjust({"adjustment_type": "inflow", "currency": CCY, "amount": 100,
                 "method": "transfer", "source_name": f"{MARK} aporte"})
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {f"vip_balances.{CCY}": 30.0}})
        try:
            r = _cw_create({"currency": CCY, "amount": 80,
                            "beneficiary": f"{MARK} A", "concept": "x"})
            assert r.status_code == 400, \
                f"80 > 70 disponibles (custodia 30) debe rechazarse: {r.status_code}"
            assert "custodia" in r.json()["detail"].lower(), r.json()
            a = _cw_create({"currency": CCY, "amount": 70,
                            "beneficiary": f"{MARK} B", "concept": "x"})
            assert a.status_code == 200, a.text
            r = _cw_status(a.json()["id"], {"status": "paid"})
            assert r.status_code == 200, r.text
            # pagar más que el disponible real también se bloquea al pagar
            db.users.update_one({"user_id": "user_test_vip01"},
                                {"$set": {f"vip_balances.{CCY}": 40.0}})
            c = _cw_create({"currency": CCY, "amount": 5,
                            "beneficiary": f"{MARK} C", "concept": "x"})
            assert c.status_code == 400, \
                "balance 30 − custodia 40 → disponible negativo: nada se autoriza"
        finally:
            db.users.update_one({"user_id": "user_test_vip01"},
                                {"$unset": {f"vip_balances.{CCY}": ""}})


class TestH01LedgerCashParity:
    def teardown_method(self, _):
        _cleanup()

    def test_paid_cash_withdrawal_and_transfers_hit_the_physical_box(self):
        """Aceptación del auditor: aporte, retiro pagado y transferencia se
        reflejan en la caja física; la transferencia no cambia el capital."""
        _cleanup()
        db = _db()
        _run_backfill()  # V02 — drenar históricos pendientes para aislar el delta
        box = _auto_box()
        base_bal = _resumen(box["id"], "USD")["balance"] if box else 0.0

        # aporte de 200 USD en efectivo (entrada física, ya cubierto iter263)
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 200, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"100": 2}})
        assert r.status_code == 200, r.text

        # retiro de 40 USD pagado desde la cuenta de caja → salida física
        cash_acc = db.fund_accounts.find_one(
            {"name": "Fondo Resilience", "method": "cash", "currency": "USD"},
            {"_id": 0, "id": 1})
        assert cash_acc, "la cuenta de caja USD debe existir"
        # V06 — datos aislados: disponible real suficiente tras custodia y reservas
        _ensure_usd_available(45)
        cwr = _cw_create({"currency": "USD", "amount": 40,
                          "beneficiary": f"{MARK} proveedor",
                          "concept": "compra insumos"})
        assert cwr.status_code == 200, cwr.text
        cw = cwr.json()
        r = _cw_status(cw["id"], {"status": "paid",
                                  "paid_from_account_id": cash_acc["id"]})
        assert r.status_code == 200, r.text
        mov_id = r.json().get("cash_box_movement_id")
        assert mov_id, "el retiro pagado en efectivo debe enlazar su movimiento"
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["type"] == "salida" and mov["amount"] == 40.0
        assert mov["fund"] == "USD"
        assert mov.get("denoms_pending") is True, \
            "sin billetes conocidos el desglose queda PENDIENTE, no inventado"
        assert mov["source_withdrawal_id"] == cw["id"]

        # transferencia caja → banco (Sin asignar): salida física,
        # capital total sin cambio
        row_before = _fund_row("USD")["balance"]
        r = requests.post(f"{API}/admin/company-funds/accounts/transfer",
                          headers=_hdr(ADMIN_TOKEN),
                          json=with_totp_admin({
                              "currency": "USD",
                              "from_account_id": cash_acc["id"],
                              "to_account_id": None, "amount": 20,
                              "note": f"{MARK} a banco"}))
        assert r.status_code == 200, r.text
        tr_mov = r.json().get("cash_box_movement_id")
        assert tr_mov, "la transferencia desde la caja debe reflejarse"
        mov = db.cash_box_movements.find_one({"id": tr_mov}, {"_id": 0})
        assert mov["type"] == "salida" and mov["amount"] == 20.0
        row_after = _fund_row("USD")["balance"]
        assert round(row_before - row_after, 2) == 0.0, \
            "una transferencia interna no cambia el capital total"

        # transferencia banco → caja: entrada física
        r = requests.post(f"{API}/admin/company-funds/accounts/transfer",
                          headers=_hdr(ADMIN_TOKEN),
                          json=with_totp_admin({
                              "currency": "USD", "from_account_id": None,
                              "to_account_id": cash_acc["id"], "amount": 5,
                              "note": f"{MARK} de banco"}))
        assert r.status_code == 200, r.text
        mov = db.cash_box_movements.find_one(
            {"id": r.json()["cash_box_movement_id"]}, {"_id": 0})
        assert mov["type"] == "entrada" and mov["amount"] == 5.0

        # paridad: la caja física se movió exactamente +200 −40 −20 +5
        box = _auto_box()
        delta = round(_resumen(box["id"], "USD")["balance"] - base_bal, 2)
        assert delta == 145.0, f"delta física {delta} ≠ 145 (H01)"

        # idempotencia: el backfill no duplica nada de lo ya espejado
        _run_backfill()
        assert db.cash_box_movements.count_documents(
            {"source_withdrawal_id": cw["id"]}) == 1

    def test_withdrawal_mirror_locked_but_denoms_completable(self):
        _cleanup()
        db = _db()
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 60, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"20": 3}})
        assert r.status_code == 200, r.text
        cash_acc = db.fund_accounts.find_one(
            {"name": "Fondo Resilience", "method": "cash", "currency": "USD"},
            {"_id": 0, "id": 1})
        # V06 — disponible real suficiente + status comprobado antes de usar ["id"]
        _ensure_usd_available(45)
        cwr = _cw_create({"currency": "USD", "amount": 40,
                          "beneficiary": f"{MARK} proveedor",
                          "concept": "x"})
        assert cwr.status_code == 200, cwr.text
        cw = cwr.json()
        pay = _cw_status(cw["id"], {"status": "paid",
                                    "paid_from_account_id": cash_acc["id"]})
        assert pay.status_code == 200, pay.text
        mov_id = pay.json()["cash_box_movement_id"]
        box = _auto_box()

        # importe/concepto bloqueados; borrado bloqueado
        r = requests.put(f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
                         headers=_hdr(ADMIN_TOKEN), json={"amount": 1})
        assert r.status_code == 409, r.text
        r = requests.delete(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 409, r.text

        # …pero el desglose PENDIENTE sí puede completarse (una sola vez)
        r = requests.put(f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"denominations": {"20": 2}})
        assert r.status_code == 200, r.text
        mov = _db().cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}
        assert mov.get("denoms_pending") is False
        r = requests.put(f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"denominations": {"10": 4}})
        assert r.status_code == 409, "el desglose completado ya no se reescribe"

    def test_direct_box_movement_is_flagged_sin_contrapartida(self):
        _cleanup()
        box = _auto_box()
        assert box, "la caja del sistema debe existir"
        mov = _mk_mov(box["id"], 50, {"50": 1}, fund="CUP")
        assert mov.get("ledger_status") == "sin_contrapartida", \
            "un movimiento directo en la caja del sistema queda pendiente de conciliar"
        res = _resumen(box["id"], "CUP")
        sc = res.get("sin_contrapartida") or {}
        assert sc.get("count", 0) >= 1
        assert sc.get("entradas", 0) >= 50.0


class TestH03BoxIdentity:
    def test_rename_does_not_split_history(self):
        _cleanup()
        db = _db()
        box = _auto_box()
        assert box, "la caja del sistema debe existir"
        original_name = box["name"]
        try:
            r = requests.put(f"{API}/cashbox/boxes/{box['id']}",
                             headers=_hdr(ADMIN_TOKEN),
                             json={"name": f"Caja Central {MARK}"})
            assert r.status_code == 200, r.text
            # un ajuste en efectivo tras el renombre usa la MISMA caja
            r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                         "amount": 10, "method": "cash",
                         "source_name": f"{MARK} aporte",
                         "denominations": {"10": 1}})
            assert r.status_code == 200, r.text
            mov = db.cash_box_movements.find_one(
                {"id": r.json()["cash_box_movement_id"]}, {"_id": 0})
            assert mov["box_id"] == box["id"], \
                "renombrar la caja no puede desviar los espejos a otra caja"
            assert db.cash_boxes.count_documents(
                {"system_purpose": "company_cash"}) == 1, \
                "identidad única de la caja del sistema (H03)"
        finally:
            requests.put(f"{API}/cashbox/boxes/{box['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"name": original_name})
            _cleanup()


class TestH04EarlyArqueo:
    def teardown_method(self, _):
        _cleanup()

    def test_movements_after_arqueo_reopen_the_request(self):
        box = _mk_box()
        _mk_mov(box["id"], 100, {"100": 1})
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/arqueos",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"fund": "CUP", "counted": {"100": 1}})
        assert r.status_code == 200, r.text
        assert _resumen(box["id"])["needs_arqueo"] is False

        # movimiento POSTERIOR al conteo → el arqueo temprano ya no es cierre
        _mk_mov(box["id"], 40, {"20": 2}, mtype="salida")
        res = _resumen(box["id"])
        assert res["needs_arqueo"] is True, \
            "un arqueo temprano no tapa los movimientos posteriores (H04)"
        assert (res["arqueo_today"] or {}).get("superseded") is True

        async def flow():
            from services.cash_box_arqueo import pending_arqueo_funds
            box_doc = _db().cash_boxes.find_one({"id": box["id"]}, {"_id": 0})
            return await pending_arqueo_funds(box_doc)
        pend = _run(flow)
        assert any(p["fund"] == "CUP" for p in pend), \
            "el job diario también debe volver a pedir el conteo"

        # nuevo arqueo tras el último movimiento → cierre vigente
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/arqueos",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"fund": "CUP", "counted": {"20": 3}})
        assert r.status_code == 200 and r.json()["status"] == "cuadrada"
        res = _resumen(box["id"])
        assert res["needs_arqueo"] is False
        assert (res["arqueo_today"] or {}).get("superseded") is False


class TestH05DenomKeyConsolidation:
    def teardown_method(self, _):
        _cleanup()

    def test_equivalent_keys_are_consolidated_everywhere(self):
        db = _db()
        box = _mk_box()
        # movimiento: {"100": 1, "100.0": 1} = 200 → debe guardar {"100": 2}
        mov = _mk_mov(box["id"], 200, {"100": 1, "100.0": 1})
        assert mov["denominations"] == {"100": 2}, mov["denominations"]

        # arqueo con claves equivalentes: el conteo persistido suma 200
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/arqueos",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"fund": "CUP",
                                "counted": {"100": 1, "100.0": 1}})
        assert r.status_code == 200, r.text
        arq = r.json()
        assert arq["total_counted"] == 200.0
        assert arq["counted"]["100"] == 2 if "counted" in arq else True
        assert arq["status"] == "cuadrada", \
            "200 contados contra 200 de sistema deben cuadrar"

        # desglose de cuenta contable (Fondo Resilience USD)
        acc = db.fund_accounts.find_one(
            {"name": "Fondo Resilience", "method": "cash", "currency": "USD"},
            {"_id": 0, "id": 1})
        if acc:
            r = requests.post(
                f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
                headers=_hdr(ADMIN_TOKEN),
                json={"denominations": {"1": 1, "1.0": 2},
                      "note": f"{MARK} consolidación"})
            assert r.status_code == 200, r.text
            snap = r.json()
            assert snap["denominations"] == {"1": 3}, snap["denominations"]
            assert snap["total"] == 3.0


class TestH06NoSilentCaps:
    def teardown_method(self, _):
        _cleanup()

    def test_monthly_report_counts_beyond_20000(self):
        db = _db()
        box = _mk_box()
        now_utc_dt = datetime.now(timezone.utc)
        month = now_utc_dt.astimezone(
            ZoneInfo("America/Havana")).strftime("%Y-%m")
        docs = [{"id": f"cmov_{MARK}_{i}", "box_id": box["id"], "fund": "CUP",
                 "type": "entrada", "amount": 1.0,
                 "concept": f"seed {MARK}", "responsible": "",
                 "created_at": now_utc_dt.isoformat(),
                 "created_by_id": "t", "created_by_name": "t"}
                for i in range(20050)]
        db.cash_box_movements.insert_many(docs)
        r = requests.get(f"{API}/cashbox/boxes/{box['id']}/reporte",
                         params={"fund": "CUP", "month": month},
                         headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["num_movimientos"] == 20050, \
            f"el reporte debe contar TODOS los movimientos: {rep['num_movimientos']}"
        assert rep["total_entradas"] == 20050.0


class TestH07InitialImmutableAfterOps:
    def teardown_method(self, _):
        _cleanup()

    def test_initial_locked_once_operations_exist(self):
        db = _db()
        box = _mk_box()
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/inicial",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"fund": "CUP", "amount": 100,
                                "denominations": {"100": 1}})
        assert r.status_code == 200, r.text
        # sin operativa: corregir el inicial se permite y deja historial
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/inicial",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"fund": "CUP", "amount": 500,
                                "denominations": {"500": 1}})
        assert r.status_code == 200, r.text
        fresh = db.cash_boxes.find_one({"id": box["id"]}, {"_id": 0})
        hist = (fresh.get("initial_history") or {}).get("CUP") or []
        assert len(hist) == 1 and hist[0]["prev_amount"] == 100.0, \
            "la corrección pre-operativa queda en el historial (H07)"

        # con operativa: el inicial es inmutable
        _mk_mov(box["id"], 50, {"50": 1})
        r = requests.post(f"{API}/cashbox/boxes/{box['id']}/inicial",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"fund": "CUP", "amount": 9999})
        assert r.status_code == 409, \
            f"reescribir el inicial con operativa debe bloquearse: {r.status_code}"
        assert "corrección" in r.json()["detail"].lower()
        fresh = db.cash_boxes.find_one({"id": box["id"]}, {"_id": 0})
        assert fresh["initial"]["CUP"]["amount"] == 500.0
        assert _resumen(box["id"])["balance"] == 550.0
