"""iter282 — U01 (revisión 795176e): la invalidación del arqueo debe ser
RECUPERABLE cuando falla el incremento de `fund_revs` justo después de
guardar un desglose.

La marca `rev_pending` se persiste en la MISMA escritura que los billetes
(ruta de completado, edición genérica y reparador) y el backfill la atiende
aunque origen y espejo ya coincidan. Aceptación del auditor: tras restaurar
el servicio y recuperar, el arqueo anterior queda invalidado, el desglose se
conserva, el saldo no cambia y las recuperaciones posteriores no generan
operaciones nuevas ni invalidan indefinidamente arqueos nuevos.
"""
import uuid
from datetime import datetime, timedelta, timezone

import requests

from tests.conftest import BASE_URL, ADMIN_TOKEN
from tests.test_iter279_s01_s07 import _db, _run, _run_backfill, _auto_box, \
    _resumen
from tests.test_iter270_revision_flujo_caja import _usd_denoms_for

API = f"{BASE_URL}/api"
MARK = "ITER282"


def _hdr():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}",
            "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _cleanup():
    db = _db()
    wd_ids = [w["id"] for w in db.withdrawals.find(
        {"user_name": {"$regex": MARK}}, {"id": 1})]
    db.cash_box_movements.delete_many({"$or": [
        {"concept": {"$regex": MARK}},
        {"source_client_withdrawal_id": {"$in": wd_ids}}]})
    db.withdrawals.delete_many({"id": {"$in": wd_ids}})
    db.cash_box_arqueos.delete_many({"note": MARK})


def _mk_arqueo(box_id, counted):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/arqueos", headers=_hdr(),
                      json={"fund": "USD", "counted": counted, "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()


def _closing_valid(box_id):
    async def _f():
        from services.cash_box_arqueo import closing_arqueo_status
        return await closing_arqueo_status(box_id, "USD")
    return _run(_f)


def _pending_completion_state(db, src_denoms=None):
    """Retiro de cliente pagado cuyo movimiento físico aún no tiene desglose."""
    box = _auto_box()
    wid = str(uuid.uuid4())
    mov_id = f"cmov_wd_{wid.replace('-', '')[:20]}"
    db.withdrawals.insert_one({
        "id": wid, "user_id": "user_test_normal01",
        "user_name": f"{MARK} cliente", "currency": "USD",
        "amount_usd": 40.0, "status": "paid", "method": "cash",
        "paid_from_account_id": "", "paid_at": _iso(5), "created_at": _iso(10),
        "denominations": src_denoms, "cash_box_movement_id": mov_id})
    db.cash_box_movements.insert_one({
        "id": mov_id, "box_id": box["id"], "fund": "USD", "type": "salida",
        "amount": 40.0, "concept": f"{MARK} retiro", "responsible": "Sistema",
        "denominations": None, "denoms_pending": True, "rev_bumped": True,
        "created_at": _iso(5), "created_by_id": "system",
        "created_by_name": "Sistema", "source_client_withdrawal_id": wid})
    return box, wid, mov_id


def _assert_stable_after_recovery(db, box, wid, bal_before):
    """Aceptación U01: sin operaciones nuevas y sin invalidar indefinidamente."""
    assert _resumen(box["id"], "USD")["balance"] == bal_before, \
        "el saldo no cambia: la recuperación no genera operaciones monetarias"
    assert db.cash_box_movements.count_documents(
        {"source_client_withdrawal_id": wid}) == 1, "sin duplicados"
    _run_backfill()  # drenar antes del arqueo nuevo
    bal = _resumen(box["id"], "USD")["balance"]
    _mk_arqueo(box["id"], _usd_denoms_for(bal))
    _run_backfill()
    _run_backfill()
    _, vigente = _closing_valid(box["id"])
    assert vigente is True, \
        "un arqueo nuevo sigue vigente: no se invalida indefinidamente"


class TestU01RouteCompletion:
    def teardown_method(self, _):
        _cleanup()

    def test_route_completion_invalidates_previous_closing(self):
        """Camino sin fallo: completar por la ruta invalida el cierre y no
        deja marca pendiente."""
        _cleanup()
        db = _db()
        _run_backfill()
        box, wid, mov_id = _pending_completion_state(db)
        bal = _resumen(box["id"], "USD")["balance"]
        _mk_arqueo(box["id"], _usd_denoms_for(bal))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True
        r = requests.put(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
            headers=_hdr(), json={"denominations": {"20": 2}})
        assert r.status_code == 200, r.text
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, "el cierre anterior queda invalidado"
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}
        assert "rev_pending" not in mov, "la marca se limpia tras el bump"

    def test_interrupted_route_rev_bump_recovered_by_backfill(self):
        """Variante 1 del auditor: la ruta persistió origen + espejo con la
        marca, pero murió antes de incrementar `fund_revs`. El backfill
        completa la invalidación aunque ambos desgloses ya coincidan."""
        _cleanup()
        db = _db()
        _run_backfill()
        box, wid, mov_id = _pending_completion_state(db)
        bal = _resumen(box["id"], "USD")["balance"]
        _mk_arqueo(box["id"], _usd_denoms_for(bal))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True

        # estado EXACTO que persiste la ruta antes del incremento de revisión
        db.withdrawals.update_one(
            {"id": wid}, {"$set": {"denominations": {"20": 2}}})
        db.cash_box_movements.update_one(
            {"id": mov_id},
            {"$set": {"denominations": {"20": 2}, "denoms_pending": False,
                      "rev_pending": True}})
        _, vigente = _closing_valid(box["id"])
        assert vigente is True, "sin recuperación, el cierre seguiría vigente"

        _run_backfill()
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, \
            "la recuperación completa la invalidación pendiente"
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}, "el desglose se conserva"
        assert "rev_pending" not in mov
        _assert_stable_after_recovery(db, box, wid, bal)


class TestU01ConvergeRecovery:
    def teardown_method(self, _):
        _cleanup()

    def test_interrupted_converge_rev_bump_recovered(self):
        """Variante 2 del auditor: el reparador completa el espejo desde el
        origen autorizado, pero falla el incremento de revisión. Tras
        restaurar, dos recuperaciones dejan el cierre invalidado UNA vez."""
        _cleanup()
        db = _db()
        _run_backfill()
        box, wid, mov_id = _pending_completion_state(db,
                                                     src_denoms={"20": 2})
        bal = _resumen(box["id"], "USD")["balance"]
        _mk_arqueo(box["id"], _usd_denoms_for(bal))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True

        def _fail_converge():
            async def _f():
                from services import cash_box_sync as sync
                orig = sync._bump_fund_rev

                async def boom(box_id, fund):
                    raise RuntimeError("fallo inyectado en fund_revs")

                sync._bump_fund_rev = boom
                try:
                    try:
                        await sync._converge_operation_denoms()
                        return "no-falló"
                    except RuntimeError:
                        return "falló"
                finally:
                    sync._bump_fund_rev = orig
            return _run(_f)

        assert _fail_converge() == "falló"
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}, \
            "los billetes ya quedaron persistidos"
        assert mov.get("rev_pending") is True, \
            "la marca recuperable acompaña al desglose"
        _, vigente = _closing_valid(box["id"])
        assert vigente is True, "reproduce U01: el cierre aún figura vigente"

        _run_backfill()
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, \
            "tras restaurar, la recuperación invalida el cierre anterior"
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2}
        assert mov["denoms_pending"] is False
        assert "rev_pending" not in mov
        _assert_stable_after_recovery(db, box, wid, bal)


class TestU01GenericEdit:
    def teardown_method(self, _):
        _cleanup()

    def test_generic_edit_leaves_no_pending_marker(self):
        """La edición genérica (importe/desglose de un movimiento directo)
        también viaja con la marca y la limpia tras invalidar."""
        _cleanup()
        db = _db()
        box = _auto_box()
        r = requests.post(
            f"{API}/cashbox/boxes/{box['id']}/movimientos", headers=_hdr(),
            json={"fund": "USD", "type": "entrada", "amount": 50,
                  "concept": f"{MARK} directo", "responsible": "Admin",
                  "denominations": {"50": 1}})
        assert r.status_code == 200, r.text
        mov_id = r.json()["id"]
        bal = _resumen(box["id"], "USD")["balance"]
        _mk_arqueo(box["id"], _usd_denoms_for(bal))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True
        r = requests.put(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov_id}",
            headers=_hdr(), json={"denominations": {"20": 2, "10": 1}})
        assert r.status_code == 200, r.text
        _, vigente = _closing_valid(box["id"])
        assert vigente is False
        mov = db.cash_box_movements.find_one({"id": mov_id}, {"_id": 0})
        assert mov["denominations"] == {"20": 2, "10": 1}
        assert "rev_pending" not in mov
        db.cash_box_movements.delete_one({"id": mov_id})
