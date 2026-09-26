"""iter300 — Verificación de conciliación (informe c4f993b): cierre de los
5 hallazgos parciales CB01, CB03, CB05, CB08 y CB13.

CB03 La reserva manual usa un token único por intento: una solicitud
     simultánea hacia la MISMA orden no hereda la reserva, la liberación y el
     cierre se condicionan al token propio y un cierre perdido devuelve un
     estado recuperable (nunca un éxito sin vínculo).
CB05 Cada conciliación lleva una generación única (`match_uid`); el cierre de
     una reversión solo libera ESA generación — un cierre tardío jamás borra
     un vínculo posterior.
CB13 La compatibilidad histórica reproduce EXACTAMENTE el cálculo anterior
     (sin dirección, referencia→descripción→índice) y comprueba la dirección
     del registro hallado; las filas sin fecha con identidad histórica débil
     van a revisión con ambigüedad explícita.
CB01 La coincidencia de cuenta obligatoria exige AMBOS identificadores: un
     valor ausente bloquea la confirmación.
CB08 La evidencia de apellido es independiente del orden de los nombres:
     'MANUEL JOSE' ya no satisface el requisito para 'JOSE MANUEL PEREZ'.
"""
import asyncio
import io
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api/admin/reconciliation"
MARK = "iter300"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro_fn):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _old(minutes=15):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


def _cleanup():
    db = _db()
    db.bank_transactions.delete_many({"id": {"$regex": f"^btx_{MARK}"}})
    db.orders.delete_many({"id": {"$regex": f"^ord{MARK}"}})
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": f"^{MARK}"}}, {"id": 1})]
    if imps:
        db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
        db.bank_statement_imports.delete_many({"id": {"$in": imps}})
        db.statement_files.delete_many({"id": {"$in": imps}})
    db.bank_transactions.delete_many({"sender_name": {"$regex": f"{MARK}"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def _mk_order(order_id, amount=100.0, name="ANA PEREZ", currency="USD",
              status="pending", user_id="user_test_normal01", pacc=None,
              **extra):
    doc = {
        "id": order_id, "user_id": user_id,
        "user_name": name, "user_email": f"{order_id[:10]}@test.com",
        "sender_name": name,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": currency, "to_code": "CUP", "status": status,
        "payment_account_id": pacc, "payment_account_label": "Zelle Test",
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().orders.insert_one(dict(doc))
    return doc


def _mk_tx(tx_id, amount=100.0, currency="USD", direction="credit",
           status="unmatched", sender="ANA PEREZ", **extra):
    doc = {
        "id": tx_id, "statement_import_id": f"{MARK}_imp_seed",
        "bank_account_id": None, "bank_name": "Test Bank",
        "currency": currency, "direction": direction, "amount": float(amount),
        "transaction_date": _now()[:10], "sender_name": sender,
        "description": None, "reference": None,
        "fingerprint": f"fp_{tx_id}_{uuid.uuid4().hex[:8]}",
        "fingerprint_original": f"fpo_{tx_id}",
        "status": status, "confidence_score": None,
        "matched_order_id": None, "match_details": None, "candidates": [],
        "reviewed_by": None, "reviewed_at": None, "raw": {},
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().bank_transactions.insert_one(dict(doc))
    return doc


def _confirm(tx_id, order_id, token=ADMIN):
    return requests.post(f"{API}/transactions/{tx_id}/confirm",
                         headers=_h(token), json={"order_id": order_id})


def _rollback(tx_id, reason="prueba de reversión"):
    return requests.post(f"{API}/transactions/{tx_id}/rollback",
                         headers=_h(ADMIN), json={"reason": reason})


# ---------------------------------------------------------------------------
# CB03 — reserva manual con token exclusivo por intento
# ---------------------------------------------------------------------------
class TestCB03ManualClaimToken:
    def test_active_same_order_claim_is_not_inherited(self):
        """Reproducción manual_claim_race (paso 2): una segunda solicitud
        hacia la MISMA orden encuentra la reserva activa de la primera — ya
        NO la hereda ni continúa: 409 sin tocar la reserva ni acreditar."""
        oid = f"ord{MARK}m1"
        _mk_order(oid)
        winner = {"order_id": oid, "at": _now(), "by": "op1", "token": "tokWIN"}
        tx = _mk_tx(f"btx_{MARK}_m1", matching_claim=winner)
        r = _confirm(tx["id"], oid)
        assert r.status_code == 409, r.text
        fresh = _db().bank_transactions.find_one({"id": tx["id"]})
        assert (fresh.get("matching_claim") or {}).get("token") == "tokWIN", \
            "la reserva del intento activo debe permanecer intacta"
        assert _db().orders.find_one({"id": oid})["status"] == "pending"

    def test_release_only_with_own_token(self):
        """La liberación del perdedor jamás borra la reserva del ganador."""
        winner = {"order_id": "ordX", "at": _now(), "by": "op1",
                  "token": "tokWIN"}
        tx = _mk_tx(f"btx_{MARK}_m2", matching_claim=winner)

        async def flow():
            from routes.reconciliation import _release_bank_claim
            from db_client import db as adb
            await _release_bank_claim(tx["id"], "tokLOSER")
            mid = await adb.bank_transactions.find_one({"id": tx["id"]},
                                                       {"_id": 0})
            await _release_bank_claim(tx["id"], "tokWIN")
            end = await adb.bank_transactions.find_one({"id": tx["id"]},
                                                       {"_id": 0})
            return mid, end
        mid, end = _run(flow)
        assert (mid.get("matching_claim") or {}).get("token") == "tokWIN", \
            "un token ajeno jamás libera la reserva"
        assert "matching_claim" not in end

    def test_second_order_blocked_while_claim_active(self):
        """Paso 5 de la reproducción: con la reserva del ganador intacta, la
        confirmación de la orden B queda bloqueada — crédito único."""
        oid_a, oid_b = f"ord{MARK}m3a", f"ord{MARK}m3b"
        _mk_order(oid_a)
        _mk_order(oid_b)
        tx = _mk_tx(f"btx_{MARK}_m3", matching_claim={
            "order_id": oid_a, "at": _now(), "by": "op1", "token": "tokWIN"})
        r = _confirm(tx["id"], oid_b)
        assert r.status_code == 409, r.text
        assert _db().orders.find_one({"id": oid_b})["status"] == "pending"

    def test_legitimate_resume_takes_over_interrupted_claim(self):
        """Reanudación legítima (decisión persistida: orden aprobada con
        sello): el reintento toma el reclamo interrumpido y completa el
        vínculo sin doble crédito."""
        oid = f"ord{MARK}m4"
        tx = _mk_tx(f"btx_{MARK}_m4", matching_claim={
            "order_id": oid, "at": _old(2), "by": "crashed", "token": "tokOLD"})
        _mk_order(oid, status="approved",
                  reconciliation={"bank_transaction_id": tx["id"],
                                  "matched_at": _now(), "auto": False})
        r = _confirm(tx["id"], oid)
        assert r.status_code == 200, r.text
        fresh = _db().bank_transactions.find_one({"id": tx["id"]})
        assert fresh["status"] == "manual_matched"
        assert fresh["matched_order_id"] == oid
        assert fresh.get("match_uid"), "toda conciliación lleva su generación"
        assert "matching_claim" not in fresh

    def test_orphan_same_order_claim_recovers_after_timeout(self):
        """Un reclamo huérfano (viejo) hacia la misma orden con la orden aún
        pendiente se roba con garantías atómicas — el movimiento no queda
        atascado para siempre."""
        oid = f"ord{MARK}m5"
        _mk_order(oid)
        tx = _mk_tx(f"btx_{MARK}_m5", matching_claim={
            "order_id": oid, "at": _old(10), "by": "crashed", "token": "tokOLD"})
        r = _confirm(tx["id"], oid)
        assert r.status_code == 200, r.text
        assert _db().orders.find_one({"id": oid})["status"] == "approved"


# ---------------------------------------------------------------------------
# CB05 — generación única de la conciliación (match_uid)
# ---------------------------------------------------------------------------
class TestCB05MatchGeneration:
    def test_match_uid_lifecycle_and_cycles(self):
        oid_a, oid_b = f"ord{MARK}g1a", f"ord{MARK}g1b"
        _mk_order(oid_a)
        _mk_order(oid_b)
        tx = _mk_tx(f"btx_{MARK}_g1")
        assert _confirm(tx["id"], oid_a).status_code == 200
        u1 = _db().bank_transactions.find_one({"id": tx["id"]})["match_uid"]
        assert u1
        assert _rollback(tx["id"]).status_code == 200
        fresh = _db().bank_transactions.find_one({"id": tx["id"]})
        assert fresh.get("match_uid") is None
        assert _confirm(tx["id"], oid_b).status_code == 200
        u2 = _db().bank_transactions.find_one({"id": tx["id"]})["match_uid"]
        assert u2 and u2 != u1, "cada ciclo de conciliación es una generación nueva"

    def test_stale_rollback_close_cannot_free_later_link(self):
        """Reproducción stale_rollback_close: el cierre de la reversión 2
        (que leyó la generación U1) se ejecuta cuando el movimiento ya
        respalda a B con la generación U2 — la escritura condicionada lo
        DESCARTA: el vínculo con B queda intacto y C no puede acreditarse."""
        db = _db()
        oid_a, oid_b, oid_c = (f"ord{MARK}g2a", f"ord{MARK}g2b",
                               f"ord{MARK}g2c")
        _mk_order(oid_a)
        _mk_order(oid_b)
        _mk_order(oid_c)
        tx = _mk_tx(f"btx_{MARK}_g2")
        assert _confirm(tx["id"], oid_a).status_code == 200
        u1 = db.bank_transactions.find_one({"id": tx["id"]})["match_uid"]
        assert _rollback(tx["id"]).status_code == 200
        assert _confirm(tx["id"], oid_b).status_code == 200
        # cierre TARDÍO de la reversión antigua (leyó A y la generación U1):
        # misma escritura condicionada que ejecuta la ruta.
        async def stale_close():
            from db_client import db as adb
            return await adb.bank_transactions.update_one(
                {"id": tx["id"], "matched_order_id": oid_a, "match_uid": u1,
                 "status": {"$in": ["auto_matched", "manual_matched"]}},
                {"$set": {"status": "unmatched", "matched_order_id": None,
                          "matched_kind": None, "match_uid": None}})
        res = _run(stale_close)
        assert res.modified_count == 0, \
            "el cierre antiguo no debe liberar el vínculo nuevo"
        fresh = db.bank_transactions.find_one({"id": tx["id"]})
        assert fresh["status"] == "manual_matched"
        assert fresh["matched_order_id"] == oid_b, "el vínculo con B queda intacto"
        r = _confirm(tx["id"], oid_c)
        assert r.status_code == 409, "C jamás se acredita con el mismo movimiento"
        assert db.orders.find_one({"id": oid_c})["status"] == "pending"

    def test_resume_close_still_works_with_marker(self):
        """Regresión: la reanudación legítima del cierre (marcador
        last_recon_rollback + generación vigente) sigue completando."""
        db = _db()
        oid = f"ord{MARK}g3"
        tx = _mk_tx(f"btx_{MARK}_g3", status="manual_matched",
                    matched_order_id=oid, matched_kind="order",
                    match_uid="genX")
        _mk_order(oid, status="pending",
                  last_recon_rollback={"tx_id": tx["id"], "at": _now()})
        r = _rollback(tx["id"], "reanudar cierre pendiente")
        assert r.status_code == 200, r.text
        fresh = db.bank_transactions.find_one({"id": tx["id"]})
        assert fresh["status"] in ("unmatched", "manual_review")
        assert fresh["matched_order_id"] is None


# ---------------------------------------------------------------------------
# CB01 — cuenta obligatoria exige ambos identificadores
# ---------------------------------------------------------------------------
class TestCB01RequiredAccount:
    def _with_rule(self, enabled):
        r = requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"require_account_match": enabled})
        assert r.status_code == 200, r.text

    def test_unknown_bank_account_blocks_confirmation(self):
        self._with_rule(True)
        try:
            oid = f"ord{MARK}a1"
            _mk_order(oid, pacc="acc-USD")
            tx = _mk_tx(f"btx_{MARK}_a1", bank_account_id=None)
            r = _confirm(tx["id"], oid)
            assert r.status_code == 409, r.text
            assert "falta el identificador" in r.json()["detail"]
            assert _db().orders.find_one({"id": oid})["status"] == "pending"
            fresh = _db().bank_transactions.find_one({"id": tx["id"]})
            assert fresh["status"] == "unmatched"
            assert "matching_claim" not in fresh, "sin reserva al bloquear"
        finally:
            self._with_rule(False)

    def test_missing_order_account_also_blocks(self):
        self._with_rule(True)
        try:
            oid = f"ord{MARK}a2"
            _mk_order(oid, pacc=None)
            tx = _mk_tx(f"btx_{MARK}_a2", bank_account_id="acc-USD")
            r = _confirm(tx["id"], oid)
            assert r.status_code == 409, r.text
        finally:
            self._with_rule(False)

    def test_matching_accounts_still_flow(self):
        self._with_rule(True)
        try:
            oid = f"ord{MARK}a3"
            _mk_order(oid, pacc="acc-USD")
            tx = _mk_tx(f"btx_{MARK}_a3", bank_account_id="acc-USD")
            assert _confirm(tx["id"], oid).status_code == 200
        finally:
            self._with_rule(False)


# ---------------------------------------------------------------------------
# CB08 — apellido independiente del orden de los nombres
# ---------------------------------------------------------------------------
class TestCB08ReorderedNames:
    def test_reordered_given_names_do_not_prove_surname(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("MANUEL JOSE", "JOSE MANUEL PEREZ") < 0.75

    def test_no_distinguishable_surname_keeps_uncertainty(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("JOSE MANUEL", "MARIA JOSE") == 0.0

    def test_legit_cases_preserved(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("PEREZ JOSE", "Jose Perez") >= 0.75
        assert surname_similarity("JOSE M PEREZ", "JOSE MANUEL PEREZ") >= 0.75
        assert surname_similarity("OSCAR GONSALES", "Oscar Gonzalez") >= 0.75
        assert surname_similarity("ANA PEREZ GARCIA",
                                  "Ana Perez Garcia") >= 0.75

    def test_decide_sends_reordered_names_to_review(self):
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        order = {"id": "o1", "kind": "order", "user_id": "uA",
                 "user_name": "JOSE MANUEL PEREZ",
                 "sender_name": "JOSE MANUEL PEREZ",
                 "amount_from": 100.0, "from_code": "USD",
                 "created_at": "2026-09-24T00:00:00+00:00",
                 "status": "pending", "payment_reference": ""}
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "MANUEL JOSE",
              "transaction_date": "2026-09-24"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "review", d
        assert "surname_mismatch" in (d.get("block_reasons") or [])


# ---------------------------------------------------------------------------
# CB13 — compatibilidad histórica de huellas
# ---------------------------------------------------------------------------
class TestCB13LegacyFingerprints:
    def _import_csv(self, csv_text):
        db = _db()
        r = requests.post(
            f"{API}/imports", headers=_h(ADMIN),
            files={"file": (f"{MARK}_{uuid.uuid4().hex[:8]}.csv",
                            io.BytesIO(csv_text.encode()), "text/csv")},
            data={"bank_account_id": "", "bank_name": "Test Bank",
                  "currency": "USD"})
        assert r.status_code == 200, r.text
        imp_id = r.json()["id"]
        for _ in range(45):
            doc = db.bank_statement_imports.find_one({"id": imp_id})
            if doc and doc["processing_status"] not in ("uploaded", "processing"):
                break
            time.sleep(1)
        return imp_id

    def _legacy_fp(self, date, amount, ref, sender):
        from services.reconciliation_parser import fingerprint
        return fingerprint("", date, amount, "USD", ref, sender)

    def test_legacy_debit_no_longer_hides_new_credit(self):
        """Variante alta del informe: un cargo histórico (huella sin
        dirección) ya no descarta como duplicado un abono nuevo idéntico."""
        db = _db()
        sender = f"PEDRO {MARK} UNO"
        legacy = self._legacy_fp("2026-09-20", 100.0, "Transfer", sender)
        _mk_tx(f"btx_{MARK}_l1", direction="debit", status="ignored",
               sender=sender, description="Transfer", transaction_date="2026-09-20",
               bank_account_id="", fingerprint=legacy, fingerprint_original=legacy)
        imp_id = self._import_csv(
            f"Date,Amount,Name,Description\n2026-09-20,100,{sender},Transfer\n")
        new = db.bank_transactions.find_one({"statement_import_id": imp_id})
        assert new and new["direction"] == "credit"
        assert new["status"] != "duplicate", \
            "un cargo histórico no debe ocultar un abono nuevo"

    def test_legacy_same_direction_credit_still_dedupes(self):
        """Compat conservada: reimportar el mismo abono pre-migración sigue
        deduplicando (no se re-acredita)."""
        db = _db()
        sender = f"PEDRO {MARK} DOS"
        legacy = self._legacy_fp("2026-09-21", 80.0, "Transfer", sender)
        _mk_tx(f"btx_{MARK}_l2", direction="credit", status="manual_matched",
               matched_order_id="ord_hist", sender=sender, description="Transfer",
               transaction_date="2026-09-21", bank_account_id="",
               fingerprint=legacy, fingerprint_original=legacy)
        imp_id = self._import_csv(
            f"Date,Amount,Name,Description\n2026-09-21,80,{sender},Transfer\n")
        new = db.bank_transactions.find_one({"statement_import_id": imp_id})
        assert new["status"] == "duplicate", \
            "el mismo abono histórico no puede acreditarse de nuevo"

    def test_dateless_legacy_identity_is_ambiguous_not_auto(self):
        """Variante crítica del informe: una fila SIN fecha cuya identidad
        histórica (por descripción) coincide con un pago ya acreditado NO se
        acredita automáticamente ni se descarta — revisión con ambigüedad."""
        sender = f"PEDRO {MARK} TRES"
        legacy = self._legacy_fp(None, 100.0, "Zelle payment", sender)
        _mk_tx(f"btx_{MARK}_l3", direction="credit", status="manual_matched",
               matched_order_id="ord_hist2", sender=sender,
               description="Zelle payment", transaction_date=None,
               bank_account_id="", fingerprint=legacy,
               fingerprint_original=legacy)
        row = {"transaction_date": None, "amount": 100.0,
               "direction": "credit", "sender_name": sender,
               "description": "Zelle payment", "reference": None,
               "row_index": 0}
        imp = {"bank_account_id": "", "currency": "USD"}

        async def flow():
            from routes.reconciliation import _legacy_dedupe_state
            return await _legacy_dedupe_state(row, imp)
        is_dup, ambiguous = _run(flow)
        assert is_dup is False, "nunca descartar automáticamente"
        assert ambiguous is True, "la ambigüedad debe quedar explícita"

    def test_legacy_direction_mismatch_is_clean(self):
        sender = f"PEDRO {MARK} CUATRO"
        legacy = self._legacy_fp("2026-09-22", 50.0, "Pago", sender)
        _mk_tx(f"btx_{MARK}_l4", direction="debit", status="ignored",
               sender=sender, description="Pago", transaction_date="2026-09-22",
               bank_account_id="", fingerprint=legacy, fingerprint_original=legacy)
        row = {"transaction_date": "2026-09-22", "amount": 50.0,
               "direction": "credit", "sender_name": sender,
               "description": "Pago", "reference": None, "row_index": 0}
        imp = {"bank_account_id": "", "currency": "USD"}

        async def flow():
            from routes.reconciliation import _legacy_dedupe_state
            return await _legacy_dedupe_state(row, imp)
        assert _run(flow) == (False, False)

    def test_decide_blocks_auto_on_legacy_ambiguity(self):
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        order = {"id": "o1", "kind": "order", "user_id": "uA",
                 "user_name": "ANA PEREZ", "sender_name": "ANA PEREZ",
                 "amount_from": 100.0, "from_code": "USD",
                 "created_at": "2026-09-24T00:00:00+00:00",
                 "status": "pending", "payment_reference": ""}
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "ANA PEREZ", "transaction_date": "2026-09-24",
              "legacy_identity_ambiguous": True}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "review"
        assert "legacy_identity_ambiguous" in d["block_reasons"]
        clean = dict(tx)
        clean.pop("legacy_identity_ambiguous")
        assert decide(clean, ranked, DEFAULT_CONFIG, "")["decision"] == "auto"
