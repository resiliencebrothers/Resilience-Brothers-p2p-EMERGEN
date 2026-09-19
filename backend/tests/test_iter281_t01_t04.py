"""iter281 — Revisión Flujo de Caja (commit 072c391): pendientes T01–T04.

T01 Un espejo histórico de un depósito ajeno SIN la referencia inversa en el
    ajuste se recupera por `source_adjustment_id` y se anula con compensación
    (una sola vez), incluso si el ajuste ya estaba marcado «na».
T02 Los desgloses completados por la versión anterior en la Caja (sin copiar
    al retiro de cliente) se propagan al origen en la recuperación.
T03 Dos completados simultáneos con desgloses distintos: solo uno gana
    (adjudicación atómica); origen y espejo nunca divergen; el reintento del
    MISMO desglose es idempotente y el incompatible recibe conflicto.
T04 Un conteo CONOCIDO de cero billetes bloquea las salidas detalladas (no se
    trata como inventario desconocido); la excepción histórica sin conteo se
    conserva.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from tests.conftest import BASE_URL, ADMIN_TOKEN
from tests.test_iter279_s01_s07 import (
    _db, _run_backfill, _canonical_cash, _auto_box, _resumen,
    _mk_account, _insert_adj, _insert_count, _breakdown_row, _transfer,
)

API = f"{BASE_URL}/api"
MARK = "ITER281"


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _cleanup():
    db = _db()
    acc_ids = [a["id"] for a in db.fund_accounts.find(
        {"name": {"$regex": MARK}}, {"id": 1})]
    adj_ids = [a["id"] for a in db.company_fund_adjustments.find(
        {"$or": [{"source_name": {"$regex": MARK}},
                 {"note": {"$regex": MARK}}]}, {"id": 1})]
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


def _adj_with_mark(db, currency, amount, adjustment_type, account_id,
                   denoms=None, minutes_ago=0, method="cash"):
    doc = _insert_adj(db, currency, amount, adjustment_type, account_id,
                      denoms=denoms, minutes_ago=minutes_ago, method=method)
    db.company_fund_adjustments.update_one(
        {"id": doc["id"]}, {"$set": {"source_name": f"{MARK} operador"}})
    return doc


def _insert_legacy_mirror(db, box, adj, denoms=None, minutes_ago=30):
    mov_id = f"cmov_adj_{adj['id'].replace('-', '')[:20]}"
    db.cash_box_movements.insert_one({
        "id": mov_id, "box_id": box["id"], "fund": adj["currency"],
        "type": "entrada" if adj["adjustment_type"] == "inflow" else "salida",
        "amount": float(adj["amount"]),
        "concept": f"{MARK} espejo legado", "responsible": "Sistema",
        "denominations": denoms, "denoms_pending": denoms is None,
        "created_at": _iso(minutes_ago), "created_by_id": "system",
        "created_by_name": "Sistema", "source_adjustment_id": adj["id"]})
    return mov_id


class TestT01RelinkForeignDepositMirror:
    """T01 — espejo histórico sin referencia inversa: se recupera por
    source_adjustment_id, se anula UNA vez y el traslado posterior deja la
    caja consistente."""

    def teardown_method(self, _):
        _cleanup()

    def _scenario(self, db, with_na_marker):
        _run_backfill()
        canonical = _canonical_cash("USD")
        box = _auto_box()
        base = _resumen(box["id"], "USD")["balance"]
        sec = _mk_account(f"{MARK} secundaria {uuid.uuid4().hex[:4]}",
                          currency="USD")
        adj = _adj_with_mark(db, "USD", 40, "inflow", sec["id"],
                             denoms={"20": 2}, minutes_ago=30)
        mov_id = _insert_legacy_mirror(db, box, adj, denoms={"20": 2})
        if with_na_marker:
            # un backfill anterior ya lo evaluó y lo marcó «na»
            db.company_fund_adjustments.update_one(
                {"id": adj["id"]}, {"$set": {"cash_box_movement_id": "na"}})
        # estado heredado: la caja está inflada en +40
        assert _resumen(box["id"], "USD")["balance"] == round(base + 40, 2)
        return canonical, box, base, sec, adj, mov_id

    def _assert_recovered(self, db, canonical, box, base, sec, adj, mov_id):
        _run_backfill()
        adj_doc = db.company_fund_adjustments.find_one({"id": adj["id"]})
        assert adj_doc["cash_box_movement_id"] == mov_id, \
            "el vínculo inverso se recuperó por source_adjustment_id"
        annuls = list(db.cash_box_movements.find(
            {"annuls_movement_id": mov_id}, {"_id": 0}))
        assert len(annuls) == 1 and annuls[0]["amount"] == 40.0
        assert adj_doc["mirror_annulled_by"] == annuls[0]["id"]
        assert _resumen(box["id"], "USD")["balance"] == base, \
            "la caja vuelve a su valor real tras la compensación"

        # el traslado válido de esos 40 hacia la canónica suma UNA sola vez
        tr = _transfer(sec["id"], canonical["id"], 40, currency="USD",
                       denoms={"20": 2})
        assert tr.status_code == 200, tr.text
        db.fund_account_transfers.update_one(
            {"id": tr.json()["id"]}, {"$set": {"note": MARK}})
        assert _resumen(box["id"], "USD")["balance"] == round(base + 40, 2)

        # repetir la recuperación no añade compensaciones ni movimientos
        _run_backfill()
        assert db.cash_box_movements.count_documents(
            {"annuls_movement_id": mov_id}) == 1
        assert _resumen(box["id"], "USD")["balance"] == round(base + 40, 2)

    def test_missing_reverse_link_recovered_and_annulled_once(self):
        _cleanup()
        db = _db()
        args = self._scenario(db, with_na_marker=False)
        self._assert_recovered(db, *args)

    def test_na_marked_adjustment_recovered_and_annulled_once(self):
        _cleanup()
        db = _db()
        args = self._scenario(db, with_na_marker=True)
        self._assert_recovered(db, *args)


class TestT02PropagateHistoricCompletions:
    """T02 — un movimiento completado por la versión anterior (billetes en la
    Caja, no en el retiro) se propaga al origen durante la recuperación."""

    def teardown_method(self, _):
        _cleanup()

    def _paid_withdrawal(self, db, acc, amount, mov_denoms, src_denoms=None):
        box = _auto_box()
        wid = str(uuid.uuid4())
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_test_normal01",
            "user_name": f"{MARK} cliente", "currency": "USD",
            "amount_usd": float(amount), "status": "paid", "method": "cash",
            "paid_from_account_id": acc["id"], "paid_at": _iso(5),
            "created_at": _iso(10), "denominations": src_denoms,
            "cash_box_movement_id": f"cmov_wd_{wid.replace('-', '')[:20]}"})
        mov_id = f"cmov_wd_{wid.replace('-', '')[:20]}"
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "USD",
            "type": "salida", "amount": float(amount),
            "concept": f"{MARK} retiro cliente", "responsible": "Sistema",
            "denominations": mov_denoms,
            "denoms_pending": mov_denoms is None,
            "created_at": _iso(5), "created_by_id": "system",
            "created_by_name": "Sistema", "source_client_withdrawal_id": wid})
        return wid, mov_id

    def test_completed_bills_propagate_to_origin_on_upgrade(self):
        _cleanup()
        db = _db()
        _run_backfill()
        acc = _mk_account(f"{MARK} caja T02", currency="USD")
        _adj_with_mark(db, "USD", 100, "inflow", acc["id"],
                       denoms=None, minutes_ago=90, method="cash")
        _insert_count(db, acc, {"20": 5}, 100, minutes_ago=60)
        wid, _mov_id = self._paid_withdrawal(db, acc, 40, {"20": 2})

        # estado heredado: el inventario todavía no vio la salida
        cur = _breakdown_row("USD", acc["id"])["denoms_current"]
        assert cur["total"] == 100

        _run_backfill()
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w.get("denominations") == {"20": 2}, \
            "el desglose completado en Caja llegó al documento del retiro"
        cur = _breakdown_row("USD", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"20": 3} and cur["total"] == 60, \
            "cuenta e inventario quedan en 60 con 3×20 restantes"

        _run_backfill()  # segunda recuperación conserva los valores
        assert db.withdrawals.find_one(
            {"id": wid})["denominations"] == {"20": 2}
        cur = _breakdown_row("USD", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"20": 3} and cur["total"] == 60

    def test_interrupted_mirror_write_converges_from_origin(self):
        """T03 (recuperación duradera) — el origen adjudicado sin espejo
        converge: el movimiento pendiente recibe el desglose autorizado."""
        _cleanup()
        db = _db()
        _run_backfill()
        acc = _mk_account(f"{MARK} caja T03rec", currency="USD")
        _wid, mov_id = self._paid_withdrawal(db, acc, 40, None,
                                             src_denoms={"20": 2})
        _run_backfill()
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}
        assert mov["denoms_pending"] is False

    def test_conflicting_breakdowns_marked_never_overwritten(self):
        _cleanup()
        db = _db()
        _run_backfill()
        acc = _mk_account(f"{MARK} caja T02conf", currency="USD")
        wid, mov_id = self._paid_withdrawal(db, acc, 40, {"20": 2},
                                            src_denoms={"10": 4})
        _run_backfill()
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}, "el espejo no se sobrescribe"
        assert mov.get("denoms_conflict") is True, "conflicto trazable"
        assert db.withdrawals.find_one(
            {"id": wid})["denominations"] == {"10": 4}, \
            "el desglose autorizado del origen no se toca"


class TestT03AtomicCompletion:
    """T03 — dos completados simultáneos: solo uno fija la composición; el
    otro recibe conflicto. Origen y espejo siempre coinciden."""

    def teardown_method(self, _):
        _cleanup()

    def _pending_completion_state(self, db, src_denoms=None):
        box = _auto_box()
        wid = str(uuid.uuid4())
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_test_normal01",
            "user_name": f"{MARK} cliente", "currency": "USD",
            "amount_usd": 40.0, "status": "paid", "method": "cash",
            "paid_from_account_id": "", "paid_at": _iso(5),
            "created_at": _iso(10), "denominations": src_denoms})
        mov_id = f"cmov_wd_{wid.replace('-', '')[:20]}"
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "USD",
            "type": "salida", "amount": 40.0,
            "concept": f"{MARK} retiro pendiente", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": _iso(5), "created_by_id": "system",
            "created_by_name": "Sistema", "source_client_withdrawal_id": wid})
        return box, wid, mov_id

    def _complete(self, box_id, mov_id, denoms):
        return requests.put(
            f"{API}/cashbox/boxes/{box_id}/movimientos/{mov_id}",
            headers=_hdr(), json={"denominations": denoms})

    def test_concurrent_completions_only_one_wins(self):
        _cleanup()
        db = _db()
        box, wid, mov_id = self._pending_completion_state(db)
        payloads = [{"20": 2}, {"10": 4}]
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(
                lambda d: (d, self._complete(box["id"], mov_id, d)), payloads))
        codes = sorted(r.status_code for _, r in results)
        assert codes == [200, 409], f"exactamente uno gana: {codes}"
        winner = next(d for d, r in results if r.status_code == 200)
        src = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert src["denominations"] == winner
        assert mov["denominations"] == winner, \
            "origen y espejo muestran la MISMA composición"

    def test_retry_of_same_breakdown_is_idempotent(self):
        """Origen ya adjudicado (escritura del espejo interrumpida): el
        reintento del MISMO desglose converge; uno distinto recibe 409."""
        _cleanup()
        db = _db()
        box, wid, mov_id = self._pending_completion_state(
            db, src_denoms={"20": 2})
        bad = self._complete(box["id"], mov_id, {"10": 4})
        assert bad.status_code == 409, bad.text
        ok = self._complete(box["id"], mov_id, {"20": 2})
        assert ok.status_code == 200, ok.text
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}
        assert mov["denoms_pending"] is False
        assert db.withdrawals.find_one(
            {"id": wid})["denominations"] == {"20": 2}


class TestT04KnownZeroCount:
    """T04 — un conteo explícito de CERO billetes es inventario conocido:
    bloquea las salidas detalladas hasta reponer; la excepción histórica sin
    conteo se conserva."""

    def teardown_method(self, _):
        _cleanup()

    def test_zero_count_blocks_detailed_outflow(self):
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja T04", currency="USD")
        dest = _mk_account(f"{MARK} caja T04 dest", currency="USD")
        _adj_with_mark(db, "USD", 100, "inflow", acc["id"],
                       denoms=None, minutes_ago=30)

        # el servidor acepta el conteo cero como información válida
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_hdr(), json={"denominations": {}, "note": MARK})
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 0

        bad = _transfer(acc["id"], dest["id"], 20, currency="USD",
                        denoms={"20": 1})
        assert bad.status_code == 409, bad.text
        assert "billetes" in bad.json()["detail"].lower()
        assert db.fund_account_transfers.find_one(
            {"note": MARK, "status": "confirmed"}) is None, \
            "nada cambió: ni saldos ni movimientos"
        cur = _breakdown_row("USD", acc["id"])["denoms_current"]
        assert cur["denominations"] == {} and cur["total"] == 0, \
            "el inventario jamás queda en negativo"

        # tras un conteo válido con los billetes necesarios, sí se ejecuta
        r = requests.post(
            f"{API}/admin/company-funds/accounts/{acc['id']}/denominations",
            headers=_hdr(), json={"denominations": {"20": 5}, "note": MARK})
        assert r.status_code == 200, r.text
        ok = _transfer(acc["id"], dest["id"], 20, currency="USD",
                       denoms={"20": 1})
        assert ok.status_code == 200, ok.text
        cur = _breakdown_row("USD", acc["id"])["denoms_current"]
        assert cur["denominations"] == {"20": 4}

    def test_unknown_inventory_exception_preserved(self):
        """Histórico sin ningún conteo ni movimiento detallado: la salida
        sigue permitida como conciliación pendiente visible."""
        _cleanup()
        db = _db()
        acc = _mk_account(f"{MARK} caja T04 hist", currency="USD")
        dest = _mk_account(f"{MARK} caja T04 hist dest", currency="USD")
        _adj_with_mark(db, "USD", 100, "inflow", acc["id"],
                       denoms=None, minutes_ago=30)
        ok = _transfer(acc["id"], dest["id"], 20, currency="USD",
                       denoms={"20": 1})
        assert ok.status_code == 200, ok.text
