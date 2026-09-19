"""iter279 — Revisión Flujo de Caja (commit f1e3231): hallazgos S01–S07.

S01 Un depósito en OTRA cuenta de efectivo + traslado a la principal ya no se
    cuenta dos veces en Caja de Efectivo; los espejos históricos duplicados se
    anulan con compensación trazable (idempotente).
S02 El SERVIDOR exige el desglose de billetes en traslados y pagos que tocan
    efectivo (una operación bancaria sigue sin exigirlo).
S03 El desglose autorizado viaja al espejo físico; completar desde la Caja
    propaga al documento de origen exactamente una vez y un desglose
    contradictorio se rechaza.
S04 No se pueden sacar billetes que no existen en el inventario conocido.
S05 El corte del conteo usa el momento EFECTIVO del traslado (confirmed_at) y
    un conteo con traslado pendiente se rechaza.
S07 La tabla unificada tiene paginación, búsqueda y total REALES del servidor.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"
MARK = "ITER279"


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


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


def _run_backfill():
    async def _f():
        from services.cash_box_sync import backfill_cash_operations
        return await backfill_cash_operations()
    return _run(_f)


def _canonical_cash(currency):
    async def _f():
        from services.fund_accounts import get_or_create_cash_box
        return await get_or_create_cash_box(currency)
    return _run(_f)


def _auto_box():
    return _db().cash_boxes.find_one({"system_purpose": "company_cash"},
                                     {"_id": 0})


def _resumen(box_id, fund):
    r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                     params={"fund": fund}, headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup():
    db = _db()
    acc_ids = [a["id"] for a in db.fund_accounts.find(
        {"name": {"$regex": MARK}}, {"id": 1})]
    adj_ids = [a["id"] for a in db.company_fund_adjustments.find(
        {"source_name": {"$regex": MARK}}, {"id": 1})]
    tr_ids = [t["id"] for t in db.fund_account_transfers.find(
        {"note": {"$regex": MARK}}, {"id": 1})]
    cw_ids = [c["id"] for c in db.company_withdrawals.find(
        {"beneficiary": {"$regex": MARK}}, {"id": 1})]
    wd_ids = [w["id"] for w in db.withdrawals.find(
        {"user_name": {"$regex": MARK}}, {"id": 1})]
    db.cash_box_movements.delete_many({"$or": [
        {"concept": {"$regex": MARK}},
        {"source_adjustment_id": {"$in": adj_ids}},
        {"source_transfer_id": {"$in": tr_ids}},
        {"source_withdrawal_id": {"$in": cw_ids}},
        {"source_client_withdrawal_id": {"$in": wd_ids}},
    ]})
    db.fund_accounts.delete_many({"id": {"$in": acc_ids}})
    db.fund_account_denoms.delete_many({"account_id": {"$in": acc_ids}})
    db.fund_account_denoms.delete_many({"note": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"id": {"$in": adj_ids}})
    db.fund_account_transfers.delete_many({"id": {"$in": tr_ids}})
    db.company_withdrawals.delete_many({"id": {"$in": cw_ids}})
    db.withdrawals.delete_many({"id": {"$in": wd_ids}})


def _mk_account(name, currency="CUP", method="cash"):
    r = requests.post(f"{API}/admin/company-funds/accounts", headers=_hdr(),
                      json={"name": name, "currency": currency,
                            "method": method})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_bank(db, currency="CUP"):
    bid = f"facc_{uuid.uuid4().hex[:12]}"
    db.fund_accounts.insert_one({
        "id": bid, "name": f"{MARK} banco {uuid.uuid4().hex[:4]}",
        "currency": currency, "method": "bank", "is_active": True,
        "created_at": _iso()})
    return bid


def _insert_adj(db, currency, amount, adjustment_type, account_id,
                denoms=None, minutes_ago=0, method="cash", label=""):
    doc = {
        "id": str(uuid.uuid4()), "adjustment_type": adjustment_type,
        "currency": currency, "amount": float(amount), "method": method,
        "source_name": f"{MARK} operador", "source_account": "",
        "note": MARK, "account_id": account_id, "account_label": label,
        "denominations": denoms,
        "actor_id": "admin", "actor_email": "", "actor_name": "Admin",
        "created_at": _iso(minutes_ago),
    }
    db.company_fund_adjustments.insert_one(doc)
    return doc


def _insert_count(db, acc, denoms, total, minutes_ago=60):
    db.fund_account_denoms.insert_one({
        "id": f"fdnm_{uuid.uuid4().hex[:12]}", "account_id": acc["id"],
        "account_label": acc.get("name", ""), "currency": acc["currency"],
        "denominations": denoms, "total": float(total),
        "system_balance": float(total), "difference": 0.0,
        "status": "cuadrada", "note": MARK, "created_at": _iso(minutes_ago),
        "created_by_id": "admin", "created_by_name": "Admin"})


def _breakdown_row(currency, acc_id):
    r = requests.get(f"{API}/admin/company-funds/accounts/{currency}",
                     headers=_hdr())
    assert r.status_code == 200, r.text
    return next((a for a in r.json()["accounts"] if a["id"] == acc_id), None)


def _transfer(frm, to, amount, currency="CUP", denoms=None):
    body = {"currency": currency, "from_account_id": frm,
            "to_account_id": to, "amount": amount, "note": MARK,
            "totp_code": make_admin_totp()}
    if denoms is not None:
        body["denominations"] = denoms
    return requests.post(f"{API}/admin/company-funds/accounts/transfer",
                         headers=_hdr(), json=body)


class TestS01BoxCountsOnce:
    """S01 — depósito en cuenta secundaria + traslado a la canónica: la Caja
    de Efectivo sube UNA sola vez (nunca 100 → 180 desde 140)."""

    def teardown_method(self, _):
        _cleanup()

    def test_secondary_deposit_then_transfer_counted_once(self):
        _cleanup()
        db = _db()
        _run_backfill()  # drenar pendientes ajenos
        canonical = _canonical_cash("USD")
        box = _auto_box()
        assert box
        base = _resumen(box["id"], "USD")["balance"]

        sec = _mk_account(f"{MARK} caja secundaria", currency="USD")
        r = requests.post(
            f"{API}/admin/company-funds/adjustments", headers=_hdr(),
            json={"adjustment_type": "inflow", "currency": "USD",
                  "amount": 40, "method": "cash",
                  "source_name": f"{MARK} socio", "account_id": sec["id"],
                  "denominations": {"20": 2},
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        adj_id = r.json()["id"]

        # el depósito en cuenta AJENA no entra en la Caja de Efectivo
        assert db.cash_box_movements.find_one(
            {"source_adjustment_id": adj_id}) is None
        assert _resumen(box["id"], "USD")["balance"] == base

        # el traslado hacia la canónica genera exactamente UNA entrada física
        tr = _transfer(sec["id"], canonical["id"], 40, currency="USD",
                       denoms={"20": 2})
        assert tr.status_code == 200, tr.text
        trid = tr.json()["id"]
        movs = list(db.cash_box_movements.find(
            {"source_transfer_id": trid}, {"_id": 0}))
        assert len(movs) == 1 and movs[0]["type"] == "entrada"
        assert _resumen(box["id"], "USD")["balance"] == round(base + 40, 2)

        # el recuperador no añade movimientos (idempotente)
        _run_backfill()
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 1
        assert db.cash_box_movements.find_one(
            {"source_adjustment_id": adj_id, "annuls_movement_id":
             {"$exists": False}}) is None
        assert _resumen(box["id"], "USD")["balance"] == round(base + 40, 2)

    def test_backfill_annuls_foreign_account_mirror(self):
        """Reparación histórica: un espejo generado con la regla anterior se
        anula con compensación trazable, exactamente una vez."""
        _cleanup()
        db = _db()
        _run_backfill()
        box = _auto_box()
        base = _resumen(box["id"], "USD")["balance"]

        sec = _mk_account(f"{MARK} caja ajena", currency="USD")
        adj = _insert_adj(db, "USD", 25, "inflow", sec["id"],
                          denoms={"5": 5}, minutes_ago=30)
        mov_id = f"cmov_adj_{adj['id'].replace('-', '')[:20]}"
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "USD",
            "type": "entrada", "amount": 25.0,
            "concept": f"{MARK} espejo legado", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": _iso(30), "created_by_id": "system",
            "created_by_name": "Sistema", "source_adjustment_id": adj["id"]})
        db.company_fund_adjustments.update_one(
            {"id": adj["id"]}, {"$set": {"cash_box_movement_id": mov_id}})
        assert _resumen(box["id"], "USD")["balance"] == round(base + 25, 2)

        _run_backfill()
        annul = db.cash_box_movements.find_one(
            {"annuls_movement_id": mov_id}, {"_id": 0})
        assert annul and annul["type"] == "salida" and annul["amount"] == 25.0
        assert db.company_fund_adjustments.find_one(
            {"id": adj["id"]})["mirror_annulled_by"] == annul["id"]
        assert _resumen(box["id"], "USD")["balance"] == base

        _run_backfill()  # idempotente
        assert db.cash_box_movements.count_documents(
            {"annuls_movement_id": mov_id}) == 1
        assert _resumen(box["id"], "USD")["balance"] == base


class TestS02MandatoryBreakdown:
    """S02 — el desglose es OBLIGATORIO en el servidor cuando sale o entra
    efectivo; las operaciones bancarias no lo exigen."""

    def teardown_method(self, _):
        _cleanup()

    def test_cash_transfer_without_bills_rejected(self):
        _cleanup()
        db = _db()
        a = _mk_account(f"{MARK} caja origen")
        b = _mk_account(f"{MARK} caja destino")
        _insert_adj(db, "CUP", 5000, "inflow", a["id"],
                    denoms={"1000": 5}, minutes_ago=10)
        r = _transfer(a["id"], b["id"], 2000)
        assert r.status_code == 400, r.text
        assert "desglose" in r.json()["detail"].lower()
        assert db.fund_account_transfers.find_one({"note": MARK}) is None
        cur = _breakdown_row("CUP", a["id"])["denoms_current"]
        assert cur["denominations"] == {"1000": 5}, "nada cambió"

    def test_bank_transfer_without_bills_still_works(self):
        _cleanup()
        db = _db()
        a = _mk_bank(db)
        b = _mk_bank(db)
        _insert_adj(db, "CUP", 3000, "inflow", a, method="transfer",
                    minutes_ago=10)
        r = _transfer(a, b, 1000)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "confirmed"

    def test_cash_payment_without_bills_rejected(self):
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja pagos")
        _insert_adj(db, "CUP", 500, "inflow", acc["id"],
                    denoms={"100": 5}, minutes_ago=15)
        big = _insert_adj(db, "CUP", 1_000_000, "inflow", "",
                          method="transfer", minutes_ago=20)
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(),
            json={"amount": 300, "currency": "CUP",
                  "beneficiary": f"{MARK} proveedor", "concept": "servicio",
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        cwid = r.json()["id"]
        bad = requests.put(
            f"{API}/admin/company-withdrawals/{cwid}/status", headers=_hdr(),
            json={"status": "paid", "paid_from_account_id": acc["id"],
                  "totp_code": make_admin_totp()})
        assert bad.status_code == 400, bad.text
        assert "desglose" in bad.json()["detail"].lower()
        assert db.company_withdrawals.find_one(
            {"id": cwid})["status"] == "pending"
        db.company_fund_adjustments.delete_one({"id": big["id"]})


class TestS03BreakdownPropagation:
    """S03 — una sola fuente de verdad para el desglose: viaja al espejo y
    completar desde la Caja lo propaga al documento de origen."""

    def teardown_method(self, _):
        _cleanup()

    def test_paid_withdrawal_mirror_carries_bills(self):
        _cleanup()
        db = _db()
        _run_backfill()
        cash = _canonical_cash("CUP")
        _insert_adj(db, "CUP", 500, "inflow", cash["id"],
                    denoms={"100": 5}, minutes_ago=15)
        big = _insert_adj(db, "CUP", 1_000_000, "inflow", "",
                          method="transfer", minutes_ago=20)
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(),
            json={"amount": 300, "currency": "CUP",
                  "beneficiary": f"{MARK} espejo", "concept": "servicio",
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        cwid = r.json()["id"]
        ok = requests.put(
            f"{API}/admin/company-withdrawals/{cwid}/status", headers=_hdr(),
            json={"status": "paid", "paid_from_account_id": cash["id"],
                  "denominations": {"100": 3},
                  "totp_code": make_admin_totp()})
        assert ok.status_code == 200, ok.text
        mov = db.cash_box_movements.find_one(
            {"source_withdrawal_id": cwid}, {"_id": 0})
        assert mov, "el pago desde la caja canónica genera espejo físico"
        assert mov["denominations"] == {"100": 3}
        assert mov.get("denoms_pending") is False, \
            "el desglose autorizado viaja al espejo: nada queda pendiente"
        db.company_fund_adjustments.delete_one({"id": big["id"]})

    def test_completing_client_withdrawal_updates_inventory_once(self):
        _cleanup()
        db = _db()
        box = _auto_box()
        acc = _mk_account(f"{MARK} caja clientes")
        _insert_count(db, acc, {"200": 5}, 1000, minutes_ago=60)

        wid = str(uuid.uuid4())
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_test_normal01",
            "user_name": f"{MARK} cliente", "currency": "CUP",
            "amount_usd": 400.0, "status": "paid", "method": "cash",
            "paid_from_account_id": acc["id"], "paid_at": _iso(5),
            "created_at": _iso(10)})
        mov_id = f"cmov_wd_{wid.replace('-', '')[:20]}"
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "CUP",
            "type": "salida", "amount": 400.0,
            "concept": f"{MARK} retiro cliente", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": _iso(5), "created_by_id": "system",
            "created_by_name": "Sistema", "source_client_withdrawal_id": wid})

        r = requests.put(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
            headers=_hdr(), json={"denominations": {"200": 2}})
        assert r.status_code == 200, r.text

        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w.get("denominations") == {"200": 2}, \
            "el desglose completado en Caja llegó al documento del retiro"
        cur = _breakdown_row("CUP", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"200": 3}, \
            "el inventario por cuenta restó los billetes exactamente una vez"

    def test_conflicting_breakdown_rejected(self):
        _cleanup()
        db = _db()
        box = _auto_box()
        cwid = str(uuid.uuid4())
        db.company_withdrawals.insert_one({
            "id": cwid, "amount": 400.0, "currency": "CUP",
            "beneficiary": f"{MARK} conflicto", "concept": "",
            "status": "paid", "denominations": {"100": 4},
            "paid_at": _iso(5), "created_at": _iso(10),
            "authorized_by_id": "admin", "authorized_by_name": "Admin"})
        mov_id = f"cmov_cw_{cwid.replace('-', '')[:20]}"
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "CUP",
            "type": "salida", "amount": 400.0,
            "concept": f"{MARK} retiro empresa", "responsible": "Admin",
            "denominations": None, "denoms_pending": True,
            "created_at": _iso(5), "created_by_id": "system",
            "created_by_name": "Sistema", "source_withdrawal_id": cwid})
        r = requests.put(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
            headers=_hdr(), json={"denominations": {"200": 2}})
        assert r.status_code == 409, r.text
        assert "distinto" in r.json()["detail"].lower()
        assert db.cash_box_movements.find_one(
            {"id": mov_id})["denoms_pending"] is True


class TestS04BillsAvailability:
    """S04 — con 5×20 y ningún billete de 10, pedir 4×10 se rechaza sin
    cambios; 2×20 se acepta. Cubre traslados y pagos."""

    def teardown_method(self, _):
        _cleanup()

    def test_transfer_cannot_spend_missing_bills(self):
        _cleanup()
        db = _db()
        a = _mk_account(f"{MARK} caja S04", currency="USD")
        b = _mk_account(f"{MARK} caja S04 dest", currency="USD")
        _insert_adj(db, "USD", 100, "inflow", a["id"],
                    denoms={"20": 5}, minutes_ago=10)
        _insert_count(db, a, {"20": 5}, 100, minutes_ago=5)

        bad = _transfer(a["id"], b["id"], 40, currency="USD",
                        denoms={"10": 4})
        assert bad.status_code == 409, bad.text
        assert "billetes" in bad.json()["detail"].lower()
        cur = _breakdown_row("USD", a["id"])["denoms_current"]
        assert cur["denominations"] == {"20": 5}, \
            "nunca se presenta una composición negativa"
        assert db.fund_account_transfers.find_one(
            {"note": MARK, "status": "confirmed"}) is None

        ok = _transfer(a["id"], b["id"], 40, currency="USD",
                       denoms={"20": 2})
        assert ok.status_code == 200, ok.text
        cur = _breakdown_row("USD", a["id"])["denoms_current"]
        assert cur["denominations"] == {"20": 3}

    def test_payment_cannot_spend_missing_bills(self):
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja S04 pago")
        _insert_adj(db, "CUP", 1000, "inflow", acc["id"],
                    denoms={"200": 5}, minutes_ago=10)
        _insert_count(db, acc, {"200": 5}, 1000, minutes_ago=5)
        big = _insert_adj(db, "CUP", 1_000_000, "inflow", "",
                          method="transfer", minutes_ago=20)
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(),
            json={"amount": 400, "currency": "CUP",
                  "beneficiary": f"{MARK} sin billetes", "concept": "x",
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        cwid = r.json()["id"]
        bad = requests.put(
            f"{API}/admin/company-withdrawals/{cwid}/status", headers=_hdr(),
            json={"status": "paid", "paid_from_account_id": acc["id"],
                  "denominations": {"100": 4},
                  "totp_code": make_admin_totp()})
        assert bad.status_code == 409, bad.text
        assert db.company_withdrawals.find_one(
            {"id": cwid})["status"] == "pending"
        db.company_fund_adjustments.delete_one({"id": big["id"]})


class TestS05CountCutoff:
    """S05 — el conteo y las transferencias usan un corte consistente."""

    def teardown_method(self, _):
        _cleanup()

    def test_count_rejected_while_transfer_pending(self):
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja S05")
        db.fund_account_transfers.insert_one({
            "id": str(uuid.uuid4()), "currency": "CUP",
            "from_account_id": acc["id"], "from_label": acc["name"],
            "to_account_id": "", "to_label": "", "amount": 40.0,
            "note": MARK, "denominations": {"20": 2},
            "actor_id": "admin", "actor_name": "Admin",
            "created_at": _iso(0), "status": "pending",
            "operation_id": str(uuid.uuid4())})
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_hdr(), json={"denominations": {"20": 5}, "note": MARK})
        assert r.status_code == 409, r.text
        assert "traslado" in r.json()["detail"].lower()

    def test_cutoff_uses_effective_confirmation_moment(self):
        """Transferencia iniciada ANTES del conteo pero confirmada DESPUÉS →
        sí resta; confirmada antes → no; histórica sin confirmed_at → corte
        por created_at."""
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja corte", currency="USD")
        _insert_count(db, acc, {"20": 5}, 100, minutes_ago=60)

        def _tr(created_ago, confirmed_ago, denoms, direction="from"):
            doc = {
                "id": str(uuid.uuid4()), "currency": "USD",
                "from_account_id": acc["id"] if direction == "from" else "",
                "from_label": "", "to_account_id":
                    acc["id"] if direction == "to" else "", "to_label": "",
                "amount": float(sum(int(k) * v for k, v in denoms.items())),
                "note": MARK, "denominations": denoms,
                "actor_id": "admin", "actor_name": "Admin",
                "created_at": _iso(created_ago), "status": "confirmed",
                "operation_id": str(uuid.uuid4())}
            if confirmed_ago is not None:
                doc["confirmed_at"] = _iso(confirmed_ago)
            db.fund_account_transfers.insert_one(doc)

        # creada 90 min antes, confirmada 5 min después del conteo → resta
        _tr(90, 5, {"20": 2})
        # creada 90 min antes, confirmada 70 min antes (previa al conteo) → no
        _tr(90, 70, {"20": 4})
        # histórica sin confirmed_at, creada después del conteo → suma
        _tr(30, None, {"20": 1}, direction="to")

        cur = _breakdown_row("USD", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"20": 4}, \
            "5 (conteo) − 2 (confirmada después) + 1 (histórica) = 4"


class TestS07ServerSideHistory:
    """S07 — la tabla unificada busca y pagina en el SERVIDOR: cualquier
    registro antiguo es localizable y el total es real."""

    def teardown_method(self, _):
        _cleanup()

    def _get(self, **params):
        r = requests.get(f"{API}/admin/company-funds/movements",
                         headers=_hdr(), params=params)
        assert r.status_code == 200, r.text
        return r.json()

    def test_search_pagination_and_total(self):
        _cleanup()
        db = _db()
        token = f"{MARK}-{uuid.uuid4().hex[:6]}"
        for i, ago in enumerate((300, 200, 100)):
            adj = _insert_adj(db, "CUP", 10 + i, "inflow", "",
                              minutes_ago=ago, method="transfer")
            db.company_fund_adjustments.update_one(
                {"id": adj["id"]},
                {"$set": {"source_name": f"{token} dep {i}"}})
        res = self._get(q=token)
        assert res["total"] == 3 and len(res["rows"]) == 3
        assert [r["kind"] for r in res["rows"]] == ["deposit"] * 3

        page1 = self._get(q=token, skip=0, limit=2)
        page2 = self._get(q=token, skip=2, limit=2)
        assert len(page1["rows"]) == 2 and len(page2["rows"]) == 1
        assert page1["total"] == 3 and page2["total"] == 3
        ids = [r["id"] for r in page1["rows"]] + [r["id"] for r in page2["rows"]]
        assert len(set(ids)) == 3, "la paginación no repite ni omite"
        # el más antiguo (300 min) es localizable en la última página
        assert page2["rows"][0]["source_name"] == f"{token} dep 0"
        db.company_fund_adjustments.delete_many(
            {"source_name": {"$regex": token}})

    def test_tipo_and_status_filters(self):
        _cleanup()
        db = _db()
        token = f"{MARK}-{uuid.uuid4().hex[:6]}"
        adj = _insert_adj(db, "CUP", 33, "inflow", "", minutes_ago=10,
                          method="transfer")
        db.company_fund_adjustments.update_one(
            {"id": adj["id"]}, {"$set": {"source_name": f"{token} depo"}})
        out = _insert_adj(db, "CUP", 44, "outflow", "", minutes_ago=8,
                          method="transfer")
        db.company_fund_adjustments.update_one(
            {"id": out["id"]}, {"$set": {"source_name": f"{token} salida"}})
        cwid = str(uuid.uuid4())
        db.company_withdrawals.insert_one({
            "id": cwid, "amount": 55.0, "currency": "CUP",
            "beneficiary": f"{token} retiro", "concept": "",
            "status": "pending", "created_at": _iso(5),
            "authorized_by_id": "admin", "authorized_by_name": "Admin"})

        dep = self._get(q=token, tipo="deposits")
        assert dep["total"] == 1 and dep["rows"][0]["kind"] == "deposit"

        wds = self._get(q=token, tipo="withdrawals")
        kinds = sorted(r["kind"] for r in wds["rows"])
        assert kinds == ["adjust_out", "withdrawal"] and wds["total"] == 2

        pend = self._get(q=token, status="pending")
        assert pend["total"] == 1
        assert pend["rows"][0]["kind"] == "withdrawal"
        assert pend["rows"][0]["id"] == cwid
        db.company_fund_adjustments.delete_many(
            {"source_name": {"$regex": token}})
        db.company_withdrawals.delete_one({"id": cwid})
