"""iter298 — Auditoría de Conciliación Bancaria (informe 8a23c0b): CB01–CB14.

CB01 Confirmación manual con validación financiera: dirección crédito, moneda
     compatible, importe suficiente y cuenta compatible (si la regla aplica).
CB02 'Debit Amount' se asigna al campo débito (coincidencia exacta primero);
     un cargo nunca se interpreta como ingreso.
CB03 Escrituras condicionadas + token por intento: un rematching obsoleto no
     sobrescribe un movimiento confirmado ni libera reclamos ajenos.
CB04 Reprocesar bloquea con confirmaciones en curso y preserva movimientos
     reservados/conciliados.
CB05 El rollback verifica cada transición (orden avanzada → bloquea SIN
     liberar el cobro) y reanuda el cierre bancario tras una interrupción.
CB06 Alcance de monedas del empleado aplicado en el servidor en todas las
     rutas de conciliación.
CB07 dayfirst=False prioriza %m/%d (formato estadounidense).
CB08 Un remitente que es solo nombres de pila (prefijo) no satisface el
     requisito de apellido.
CB09 La identidad compartida se evalúa contra TODOS los candidatos.
CB10 reject/ignore protegen el estado duplicate y toda confirmación revalida
     la huella bancaria original.
CB11 /api/files/reconciliation/... exige el permiso de conciliación.
CB12 enable_ocr=false evita realmente la llamada al extractor OCR.
CB13 La huella incorpora la dirección; filas sin fecha priorizan
     referencia → índice de fila (no la descripción).
CB14 Universo de candidatos incompleto (>5000) bloquea la aprobación
     automática con razón explícita.
"""
import asyncio
import io
import os
import time
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api/admin/reconciliation"
FILES_API = f"{BASE_URL}/api/files"
MARK = "iter298"

EMP_EUR_ID = "user_test_emp298_eur"
EMP_EUR_TOKEN = f"test_session_{uuid.uuid4().hex}"
EMP_SUPPORT_ID = "user_test_emp298_sup"
EMP_SUPPORT_TOKEN = f"test_session_{uuid.uuid4().hex}"
EMP_RECON_ID = "user_test_emp298_rec"
EMP_RECON_TOKEN = f"test_session_{uuid.uuid4().hex}"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(timezone.utc).isoformat()


def setup_module():
    db = _db()
    for uid, tok, perms, curs in (
        (EMP_EUR_ID, EMP_EUR_TOKEN, ["reconciliation"], ["EUR"]),
        (EMP_SUPPORT_ID, EMP_SUPPORT_TOKEN, ["support"], []),
        (EMP_RECON_ID, EMP_RECON_TOKEN, ["reconciliation"], []),
    ):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "email": f"{uid}@test.com", "name": uid,
                      "role": "employee", "allowed_permissions": perms,
                      "allowed_currencies": curs, "totp_enabled": True}},
            upsert=True)
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid,
                      "expires_at": "2099-01-01T00:00:00+00:00"}},
            upsert=True)
    _cleanup_data()


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [EMP_EUR_ID, EMP_SUPPORT_ID, EMP_RECON_ID]}})
    db.user_sessions.delete_many({"session_token": {
        "$in": [EMP_EUR_TOKEN, EMP_SUPPORT_TOKEN, EMP_RECON_TOKEN]}})
    _cleanup_data()


def _cleanup_data():
    db = _db()
    db.bank_transactions.delete_many({"statement_import_id": {"$regex": f"^{MARK}"}})
    db.bank_statement_imports.delete_many({"id": {"$regex": f"^{MARK}"}})
    db.statement_files.delete_many({"id": {"$regex": f"^{MARK}"}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$regex": f"^{MARK}"}})
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": f"^{MARK}"}}, {"id": 1})]
    if imps:
        db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
        db.bank_statement_imports.delete_many({"id": {"$in": imps}})
        db.statement_files.delete_many({"id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": f"^ord{MARK}"}})
    db.orders.delete_many({"from_code": "XTS"})
    db.settings.delete_one({"id": "reconciliation_config"})


def _mk_order(order_id, amount, name, currency="USD", status="pending",
              user_id="user_test_normal01", sender=None, pacc=None):
    _db().orders.insert_one({
        "id": order_id, "user_id": user_id,
        "user_name": name, "user_email": f"{order_id[:10]}@test.com",
        "sender_name": sender or name,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": currency, "to_code": "CUP", "status": status,
        "payment_account_id": pacc,
        "payment_account_label": "Zelle Test",
        "created_at": _now(), "updated_at": _now(),
    })


def _mk_tx(tx_id, amount, currency="USD", direction="credit",
           status="unmatched", sender="ANA PEREZ", import_id=None, **extra):
    doc = {
        "id": tx_id,
        "statement_import_id": import_id or f"{MARK}_imp_seed",
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


# ---------------------------------------------------------------------------
# CB02 — Debit Amount nunca se interpreta como ingreso
# ---------------------------------------------------------------------------
class TestCB02DebitColumn:
    def test_map_headers_exact_first(self):
        from services.reconciliation_parser import _map_headers
        m = _map_headers(["Date", "Debit Amount", "Credit Amount",
                          "Sender", "Reference"])
        assert m["debit"] == 1
        assert m["credit"] == 2
        assert m.get("amount") is None

    def test_audit_csv_produces_debit_and_credit(self):
        from services.reconciliation_parser import parse_csv
        csv_text = ("Date,Debit Amount,Credit Amount,Sender,Reference\n"
                    "2026-09-24,100,,ANA PEREZ,TRACE-DEBIT\n"
                    "2026-09-24,,50,MARIO DIAZ,TRACE-CREDIT\n")
        txs, errors, mode = parse_csv(csv_text.encode(), dayfirst=False)
        assert errors == 0 and len(txs) == 2
        by_ref = {t["reference"]: t for t in txs}
        assert by_ref["TRACE-DEBIT"]["direction"] == "debit"
        assert by_ref["TRACE-DEBIT"]["amount"] == 100
        assert by_ref["TRACE-CREDIT"]["direction"] == "credit"
        assert by_ref["TRACE-CREDIT"]["amount"] == 50

    def test_generic_amount_sign_still_works(self):
        from services.reconciliation_parser import parse_csv
        csv_text = ("Date,Amount,Name\n"
                    "2026-09-24,-75.50,OUTFLOW GUY\n"
                    "2026-09-24,120,INFLOW GUY\n")
        txs, errors, _ = parse_csv(csv_text.encode(), dayfirst=False)
        assert errors == 0 and len(txs) == 2
        assert txs[0]["direction"] == "debit" and txs[0]["amount"] == 75.5
        assert txs[1]["direction"] == "credit" and txs[1]["amount"] == 120

    def test_spanish_exact_headers(self):
        from services.reconciliation_parser import _map_headers
        m = _map_headers(["Fecha", "Cargos", "Abonos", "Concepto"])
        assert m["debit"] == 1 and m["credit"] == 2


# ---------------------------------------------------------------------------
# CB07 — preferencia mes/día respetada en ambos sentidos
# ---------------------------------------------------------------------------
class TestCB07DateOrder:
    def test_us_preference(self):
        from services.reconciliation_parser import parse_date
        assert parse_date("09/10/2026", dayfirst=False) == "2026-09-10"

    def test_eu_preference(self):
        from services.reconciliation_parser import parse_date
        assert parse_date("09/10/2026", dayfirst=True) == "2026-10-09"

    def test_iso_and_unambiguous_unchanged(self):
        from services.reconciliation_parser import parse_date
        assert parse_date("2026-09-24", dayfirst=False) == "2026-09-24"
        assert parse_date("2026-09-24", dayfirst=True) == "2026-09-24"
        assert parse_date("25/12/2026", dayfirst=False) == "2026-12-25"
        assert parse_date("13-02-2026", dayfirst=True) == "2026-02-13"


# ---------------------------------------------------------------------------
# CB13 — huella con dirección + prioridad de referencia
# ---------------------------------------------------------------------------
class TestCB13Fingerprint:
    def test_direction_distinguishes_charge_from_deposit(self):
        from services.reconciliation_parser import fingerprint
        base = ("acc1", "2026-09-24", 100.0, "USD", "", "ANA PEREZ")
        assert fingerprint(*base, direction="credit") != \
            fingerprint(*base, direction="debit")

    def test_legacy_fingerprint_stable_without_direction(self):
        from services.reconciliation_parser import fingerprint
        base = ("acc1", "2026-09-24", 100.0, "USD", "REF1", "ANA")
        assert fingerprint(*base) == fingerprint(*base)
        assert fingerprint(*base) != fingerprint(*base, direction="credit")

    def test_fp_ref_priority_reference_then_rowindex_then_description(self):
        from routes.reconciliation import _fingerprint_ref
        assert _fingerprint_ref({"reference": "R1", "description": "d",
                                 "row_index": 0}) == "R1"
        # sin fecha y sin referencia → índice de fila (no la descripción)
        assert _fingerprint_ref({"transaction_date": None,
                                 "description": "Zelle payment",
                                 "row_index": 0}) == "row0"
        assert _fingerprint_ref({"transaction_date": None,
                                 "description": "Zelle payment",
                                 "row_index": 1}) == "row1"
        # con fecha → descripción como último recurso
        assert _fingerprint_ref({"transaction_date": "2026-09-24",
                                 "description": "Zelle payment",
                                 "row_index": 3}) == "Zelle payment"

    def test_e2e_charge_and_deposit_same_day_both_kept(self):
        """Variante A del informe: cargo -100 y abono +100 con el mismo
        remitente/día/descr sin referencia — el abono ya NO es duplicado."""
        db = _db()
        csv_text = ("Date,Amount,Name,Description\n"
                    "2026-09-20,-100,PEDRO RUIZ,pago servicios\n"
                    "2026-09-20,100,PEDRO RUIZ,pago servicios\n")
        r = requests.post(
            f"{API}/imports", headers=_h(ADMIN),
            files={"file": (f"{MARK}_cb13_{uuid.uuid4().hex[:6]}.csv",
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
        txs = list(db.bank_transactions.find({"statement_import_id": imp_id}))
        assert len(txs) == 2
        statuses = {t["direction"]: t["status"] for t in txs}
        assert statuses["debit"] == "ignored"
        assert statuses["credit"] != "duplicate", \
            "el abono no debe descartarse como duplicado del cargo"


# ---------------------------------------------------------------------------
# CB08 — el apellido no se satisface con nombres de pila
# ---------------------------------------------------------------------------
class TestCB08Surname:
    def test_given_names_prefix_is_not_surname(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("JOSE MANUEL", "JOSE MANUEL PEREZ") == 0.0

    def test_initial_prefix_is_not_surname(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("JOSE M", "JOSE MANUEL PEREZ") == 0.0

    def test_legit_cases_preserved(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("JOSE M PEREZ GARCIA",
                                  "JOSE MANUEL PEREZ GARCIA") >= 0.75
        assert surname_similarity("JOSE PEREZ", "JOSE MANUEL PEREZ") >= 0.75
        assert surname_similarity("OSCAR GONSALES", "Oscar Gonzalez") >= 0.75
        assert surname_similarity("PEREZ JOSE", "Jose Perez") >= 0.75

    def test_decide_sends_audit_case_to_review(self):
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        order = {"id": "o1", "kind": "order", "user_id": "uA",
                 "user_name": "JOSE MANUEL PEREZ",
                 "sender_name": "JOSE MANUEL PEREZ",
                 "amount_from": 100.0, "from_code": "USD",
                 "created_at": "2026-09-24T00:00:00+00:00",
                 "status": "pending", "payment_reference": ""}
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "JOSE MANUEL",
              "transaction_date": "2026-09-24"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "review"
        assert "surname_mismatch" in (d.get("block_reasons") or [])


# ---------------------------------------------------------------------------
# CB09 — la identidad compartida evalúa TODOS los candidatos
# ---------------------------------------------------------------------------
class TestCB09ThirdCandidate:
    def _orders(self):
        base = {"kind": "order", "user_name": "LUIS GOMEZ",
                "sender_name": "LUIS GOMEZ", "amount_from": 100.0,
                "from_code": "USD", "status": "pending",
                "created_at": "2026-09-24T00:00:00+00:00"}
        o1 = {**base, "id": "oA1", "user_id": "userA",
              "payment_reference": "RB-AAA111"}
        o2 = {**base, "id": "oA2", "user_id": "userA", "payment_reference": ""}
        o3 = {**base, "id": "oB1", "user_id": "userB", "payment_reference": ""}
        return [o1, o2, o3]

    def test_third_candidate_of_other_user_forces_review(self):
        """Reproducción del informe: 3 candidatos (A, A, B); solo el primero
        lleva la referencia. Antes: auto. Ahora: revisión."""
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "LUIS GOMEZ",
              "description": "pago RB-AAA111",
              "transaction_date": "2026-09-24"}
        ranked = rank_candidates(tx, self._orders(), DEFAULT_CONFIG, "", set())
        assert ranked[0]["order_id"] == "oA1"  # desempate por referencia
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "review"
        assert "same_sender_multiple_users" in (d.get("block_reasons") or [])

    def test_two_candidates_same_user_still_auto_with_reference(self):
        """Control positivo: sin usuario B, la referencia sigue resolviendo."""
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "LUIS GOMEZ",
              "description": "pago RB-AAA111",
              "transaction_date": "2026-09-24"}
        orders = [o for o in self._orders() if o["user_id"] == "userA"]
        ranked = rank_candidates(tx, orders, DEFAULT_CONFIG, "", set())
        d = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert d["decision"] == "auto", d


# ---------------------------------------------------------------------------
# CB14 — universo de candidatos incompleto bloquea el auto
# ---------------------------------------------------------------------------
class TestCB14PoolLimit:
    def test_pool_incomplete_blocks_auto(self):
        from services.reconciliation_matcher import (DEFAULT_CONFIG,
                                                     rank_candidates, decide)
        order = {"id": "o1", "kind": "order", "user_id": "uA",
                 "user_name": "ANA PEREZ", "sender_name": "ANA PEREZ",
                 "amount_from": 100.0, "from_code": "USD",
                 "created_at": "2026-09-24T00:00:00+00:00",
                 "status": "pending", "payment_reference": ""}
        tx = {"id": "t1", "amount": 100.0, "currency": "USD",
              "sender_name": "ANA PEREZ", "transaction_date": "2026-09-24"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        ok = decide(tx, ranked, DEFAULT_CONFIG, "")
        assert ok["decision"] == "auto"
        blocked = decide(tx, ranked, DEFAULT_CONFIG, "", pool_complete=False)
        assert blocked["decision"] == "review"
        assert "candidate_universe_incomplete" in blocked["block_reasons"]

    def test_load_pending_orders_detects_truncation(self):
        """5001 órdenes pendientes de una moneda → (5000 docs, completo=False)."""
        db = _db()
        docs = [{"id": f"ord{MARK}x{i}", "user_id": "u", "status": "pending",
                 "from_code": "XTS", "amount_from": 1.0,
                 "created_at": _now()} for i in range(5001)]
        db.orders.insert_many(docs)
        try:
            async def _load():
                from services.reconciliation_matcher import load_pending_orders
                return await load_pending_orders("XTS")
            loaded, complete = _run(_load())
            assert len(loaded) == 5000
            assert complete is False
        finally:
            db.orders.delete_many({"from_code": "XTS"})


# ---------------------------------------------------------------------------
# CB12 — enable_ocr controla realmente el extractor
# ---------------------------------------------------------------------------
class TestCB12OcrSwitch:
    def _blank_pdf(self):
        import fitz
        doc = fitz.open()
        doc.new_page()
        data = doc.tobytes()
        doc.close()
        return data

    def test_parse_statement_respects_disabled_ocr(self):
        from services.reconciliation_parser import parse_statement
        try:
            _run(parse_statement(self._blank_pdf(), "pdf", dayfirst=False,
                                 enable_ocr=False))
            raise AssertionError("debió rechazar el PDF escaneado sin OCR")
        except ValueError as e:
            assert "OCR" in str(e)

    def test_e2e_import_fails_with_clear_note(self):
        db = _db()
        r = requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"enable_ocr": False})
        assert r.status_code == 200, r.text
        try:
            r2 = requests.post(
                f"{API}/imports", headers=_h(ADMIN),
                files={"file": (f"{MARK}_cb12_{uuid.uuid4().hex[:6]}.pdf",
                                io.BytesIO(self._blank_pdf()), "application/pdf")},
                data={"bank_account_id": "", "bank_name": "Test Bank",
                      "currency": "USD"})
            assert r2.status_code == 200, r2.text
            imp_id = r2.json()["id"]
            doc = None
            for _ in range(45):
                doc = db.bank_statement_imports.find_one({"id": imp_id})
                if doc and doc["processing_status"] not in ("uploaded", "processing"):
                    break
                time.sleep(1)
            assert doc and doc["processing_status"] == "failed"
            assert "OCR" in (doc.get("notes") or "")
        finally:
            requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"enable_ocr": True})


# ---------------------------------------------------------------------------
# CB01 — validación financiera en la confirmación manual
# ---------------------------------------------------------------------------
class TestCB01ConfirmValidation:
    def test_insufficient_amount_rejected(self):
        oid = f"ord{MARK}c01a"
        _mk_order(oid, 100, "ANA PEREZ")
        tx = _mk_tx(f"btx_{MARK}_c01a", 1.0)
        r = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid})
        assert r.status_code == 409, r.text
        assert "insuficiente" in r.json()["detail"]
        order = _db().orders.find_one({"id": oid})
        assert order["status"] == "pending"

    def test_currency_mismatch_rejected(self):
        oid = f"ord{MARK}c01b"
        _mk_order(oid, 100, "ANA PEREZ", currency="USD")
        tx = _mk_tx(f"btx_{MARK}_c01b", 100.0, currency="EUR")
        r = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid})
        assert r.status_code == 409, r.text
        assert "moneda" in r.json()["detail"].lower()

    def test_debit_rejected_even_if_ignored(self):
        oid = f"ord{MARK}c01c"
        _mk_order(oid, 100, "ANA PEREZ")
        tx = _mk_tx(f"btx_{MARK}_c01c", 100.0, direction="debit",
                    status="ignored", ignored_reason="debit")
        r = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid})
        assert r.status_code == 409, r.text
        assert "cargo" in r.json()["detail"].lower()

    def test_account_mismatch_rejected_when_required(self):
        oid = f"ord{MARK}c01d"
        _mk_order(oid, 100, "ANA PEREZ", pacc="pacc_orden")
        tx = _mk_tx(f"btx_{MARK}_c01d", 100.0, bank_account_id="pacc_otro")
        r = requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"require_account_match": True})
        assert r.status_code == 200, r.text
        try:
            r2 = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                               headers=_h(ADMIN), json={"order_id": oid})
            assert r2.status_code == 409, r2.text
            assert "cuenta" in r2.json()["detail"].lower()
        finally:
            requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"require_account_match": False})

    def test_valid_payment_still_confirms_once(self):
        oid = f"ord{MARK}c01e"
        _mk_order(oid, 100, "ANA PEREZ")
        tx = _mk_tx(f"btx_{MARK}_c01e", 100.0)
        r = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid})
        assert r.status_code == 200, r.text
        assert _db().orders.find_one({"id": oid})["status"] == "approved"
        r2 = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                           headers=_h(ADMIN), json={"order_id": oid})
        assert r2.status_code == 409  # ya conciliado — sin doble abono


# ---------------------------------------------------------------------------
# CB10 — los duplicados no se reciclan
# ---------------------------------------------------------------------------
class TestCB10DuplicateRecycling:
    def _pair(self, suffix):
        """Movimiento original conciliado + su duplicado (misma huella)."""
        oid = f"ord{MARK}c10{suffix}"
        _mk_order(oid, 100, "ANA PEREZ")
        fpo = f"fpo_shared_{MARK}_{suffix}"
        orig = _mk_tx(f"btx_{MARK}_c10o{suffix}", 100.0,
                      fingerprint_original=fpo)
        dup = _mk_tx(f"btx_{MARK}_c10d{suffix}", 100.0, status="duplicate",
                     fingerprint_original=fpo)
        r = requests.post(f"{API}/transactions/{orig['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid})
        assert r.status_code == 200, r.text
        return orig, dup

    def test_reject_on_duplicate_blocked(self):
        _, dup = self._pair("a")
        r = requests.post(f"{API}/transactions/{dup['id']}/reject",
                          headers=_h(ADMIN), json={})
        assert r.status_code == 409, r.text
        assert _db().bank_transactions.find_one({"id": dup["id"]})["status"] == "duplicate"

    def test_ignore_on_duplicate_blocked(self):
        _, dup = self._pair("b")
        r = requests.post(f"{API}/transactions/{dup['id']}/ignore",
                          headers=_h(ADMIN), json={})
        assert r.status_code == 409, r.text
        assert _db().bank_transactions.find_one({"id": dup["id"]})["status"] == "duplicate"

    def test_recycled_duplicate_cannot_confirm_second_order(self):
        """Aunque el duplicado sea forzado a 'unmatched' (estado reciclado),
        la confirmación revalida la huella original → 409, crédito único."""
        _, dup = self._pair("c")
        _db().bank_transactions.update_one({"id": dup["id"]},
                                           {"$set": {"status": "unmatched"}})
        oid_b = f"ord{MARK}c10cb"
        _mk_order(oid_b, 100, "ANA PEREZ")
        r = requests.post(f"{API}/transactions/{dup['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid_b})
        assert r.status_code == 409, r.text
        assert "duplicado" in r.json()["detail"].lower()
        assert _db().orders.find_one({"id": oid_b})["status"] == "pending"


# ---------------------------------------------------------------------------
# CB06 — alcance de monedas del empleado en el servidor
# ---------------------------------------------------------------------------
class TestCB06CurrencyScope:
    def test_eur_employee_cannot_confirm_usd_order(self):
        oid = f"ord{MARK}c06a"
        _mk_order(oid, 100, "ANA PEREZ", currency="USD")
        tx = _mk_tx(f"btx_{MARK}_c06a", 100.0, currency="USD")
        r = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                          headers=_h(EMP_EUR_TOKEN), json={"order_id": oid})
        assert r.status_code == 403, r.text
        assert _db().orders.find_one({"id": oid})["status"] == "pending"

    def test_eur_employee_cannot_touch_usd_movement(self):
        tx = _mk_tx(f"btx_{MARK}_c06b", 50.0, currency="USD")
        for action, body in (("reject", {}), ("ignore", {}),
                             ("rollback", {"reason": "prueba scope"})):
            r = requests.post(f"{API}/transactions/{tx['id']}/{action}",
                              headers=_h(EMP_EUR_TOKEN), json=body)
            assert r.status_code == 403, f"{action}: {r.text}"

    def test_eur_employee_cannot_upload_usd_statement(self):
        r = requests.post(
            f"{API}/imports", headers=_h(EMP_EUR_TOKEN),
            files={"file": (f"{MARK}_scope.csv", io.BytesIO(b"Date,Amount\n"),
                            "text/csv")},
            data={"bank_account_id": "", "bank_name": "B", "currency": "USD"})
        assert r.status_code == 403, r.text

    def test_eur_employee_listing_scoped(self):
        _mk_tx(f"btx_{MARK}_c06c", 60.0, currency="USD")
        _mk_tx(f"btx_{MARK}_c06d", 60.0, currency="EUR")
        r = requests.get(f"{API}/transactions", headers=_h(EMP_EUR_TOKEN))
        assert r.status_code == 200, r.text
        curs = {t["currency"] for t in r.json()["items"]}
        assert "USD" not in curs
        r2 = requests.get(f"{API}/transactions", headers=_h(EMP_EUR_TOKEN),
                          params={"currency": "USD"})
        assert r2.status_code == 403

    def test_unrestricted_employee_and_admin_keep_access(self):
        tx = _mk_tx(f"btx_{MARK}_c06e", 70.0, currency="USD")
        for tok in (ADMIN, EMP_RECON_TOKEN):
            r = requests.get(f"{API}/transactions", headers=_h(tok),
                             params={"currency": "USD"})
            assert r.status_code == 200, r.text
        r3 = requests.post(f"{API}/transactions/{tx['id']}/ignore",
                           headers=_h(EMP_RECON_TOKEN), json={})
        assert r3.status_code == 200, r3.text


# ---------------------------------------------------------------------------
# CB11 — la ruta genérica de archivos exige el permiso de conciliación
# ---------------------------------------------------------------------------
class TestCB11FilesRoute:
    KEY = f"reconciliation/{MARK}-imp-x.pdf"

    def test_support_employee_gets_403(self):
        r = requests.get(f"{FILES_API}/{self.KEY}", headers=_h(EMP_SUPPORT_TOKEN))
        assert r.status_code == 403, r.text

    def test_reconciliation_staff_pass_authorization(self):
        # objeto inexistente: la autorización pasa (404 del storage, no 403)
        for tok in (ADMIN, EMP_RECON_TOKEN):
            r = requests.get(f"{FILES_API}/{self.KEY}", headers=_h(tok))
            assert r.status_code in (200, 404), r.text

    def test_eur_scoped_employee_blocked_for_usd_statement(self):
        db = _db()
        imp_id = f"{MARK}scope1"
        db.bank_statement_imports.insert_one({
            "id": imp_id, "currency": "USD", "bank_name": "B",
            "original_file_name": f"{MARK}_x.pdf",
            "processing_status": "processed", "uploaded_at": _now()})
        r = requests.get(f"{FILES_API}/reconciliation/{imp_id}.pdf",
                         headers=_h(EMP_EUR_TOKEN))
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# CB03 — exclusividad entre operaciones concurrentes
# ---------------------------------------------------------------------------
class TestCB03Exclusivity:
    def test_stale_rematch_does_not_overwrite_confirmed_movement(self):
        """Variante A: un rematch con datos viejos calcula 'manual_review'
        mientras otro operador ya confirmó — el resultado obsoleto se
        DESCARTA y el movimiento permanece conciliado."""
        db = _db()
        tx = _mk_tx(f"btx_{MARK}_c03a", 100.0)
        # el operador confirma en paralelo (estado real en la BD):
        db.bank_transactions.update_one(
            {"id": tx["id"]},
            {"$set": {"status": "manual_matched", "matched_order_id": "ordX"}})
        # el rematch antiguo (leyó 'unmatched') intenta persistir su resultado
        stale = dict(tx)  # copia con el estado viejo

        async def _apply():
            from services.reconciliation_matcher import (_match_and_apply,
                                                         get_config)
            cfg = await get_config()
            return await _match_and_apply(stale, [], cfg, "", set(),
                                          {"user_id": "sys", "role": "admin"})
        _run(_apply())
        fresh = db.bank_transactions.find_one({"id": tx["id"]})
        assert fresh["status"] == "manual_matched", \
            "el resultado obsoleto no debe sobrescribir la conciliación"
        assert fresh["matched_order_id"] == "ordX"

    def test_losing_worker_does_not_clear_winner_claim(self):
        """Variante B: el intento que NO consigue la reserva no borra el
        reclamo del ganador (limpieza condicionada por token)."""
        db = _db()
        winner_claim = {"order_id": "ordWIN", "at": _now(),
                        "by": "system_reconciliation", "token": "tokWIN"}
        tx = _mk_tx(f"btx_{MARK}_c03b", 100.0, matching_claim=winner_claim)
        oid = f"ord{MARK}c03b"
        _mk_order(oid, 100, "ANA PEREZ")

        async def _lose():
            from services.reconciliation_matcher import _apply_auto_match
            best = {"order_id": oid, "score": 100, "breakdown": {},
                    "amount_exact": True}
            pool = [{"id": oid, "kind": "order"}]
            return await _apply_auto_match(dict(tx), best, pool, {}, set(),
                                           {"user_id": "sys"}, "unmatched")
        outcome = _run(_lose())
        assert outcome == "review"
        fresh = db.bank_transactions.find_one({"id": tx["id"]})
        assert (fresh.get("matching_claim") or {}).get("token") == "tokWIN", \
            "el reclamo del ganador debe permanecer intacto"


# ---------------------------------------------------------------------------
# CB04 — reprocesar no borra movimientos reservados
# ---------------------------------------------------------------------------
class TestCB04Reprocess:
    def _mk_import(self, suffix, csv_text):
        db = _db()
        imp_id = f"{MARK}rp{suffix}"
        db.bank_statement_imports.insert_one({
            "id": imp_id, "currency": "USD", "bank_name": "Test Bank",
            "bank_account_id": None,
            "original_file_name": f"{MARK}_rp{suffix}.csv",
            "stored_file_url": f"mongo://{imp_id}", "file_type": "csv",
            "file_hash": f"h{uuid.uuid4().hex}", "uploaded_at": _now(),
            "processing_status": "processed", "notes": None})
        db.statement_files.insert_one({
            "id": imp_id, "filename": f"{MARK}_rp{suffix}.csv",
            "data": csv_text.encode(), "content_type": "text/csv"})
        return imp_id

    CSV = ("Date,Amount,Name,Reference\n"
           "2026-09-20,100,ANA PEREZ,REF-CB04\n")

    def test_reprocess_blocked_while_claim_in_progress(self):
        imp_id = self._mk_import("a", self.CSV)
        _mk_tx(f"btx_{MARK}_c04a", 100.0, import_id=imp_id,
               matching_claim={"order_id": "ordY", "at": _now(),
                               "by": "u1", "token": "t1"})
        r = requests.post(f"{API}/imports/{imp_id}/reprocess", headers=_h(ADMIN))
        assert r.status_code == 409, r.text
        assert _db().bank_transactions.find_one(
            {"id": f"btx_{MARK}_c04a"}) is not None

    def test_reprocess_preserves_matched_and_dedupes(self):
        db = _db()
        imp_id = self._mk_import("b", self.CSV)
        # movimiento ya conciliado con la MISMA huella que produce el archivo
        from services.reconciliation_parser import fingerprint
        fp = fingerprint("", "2026-09-20", 100.0, "USD", "REF-CB04",
                         "ANA PEREZ", direction="credit")
        _mk_tx(f"btx_{MARK}_c04b", 100.0, import_id=imp_id,
               status="manual_matched", matched_order_id="ordZ",
               fingerprint=fp, fingerprint_original=fp)
        r = requests.post(f"{API}/imports/{imp_id}/reprocess", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        for _ in range(45):
            doc = db.bank_statement_imports.find_one({"id": imp_id})
            if doc["processing_status"] not in ("uploaded", "processing"):
                break
            time.sleep(1)
        kept = db.bank_transactions.find_one({"id": f"btx_{MARK}_c04b"})
        assert kept and kept["status"] == "manual_matched", \
            "el movimiento conciliado debe preservarse"
        # la fila re-extraída idéntica queda como duplicate — nunca dos abonos
        twins = list(db.bank_transactions.find(
            {"statement_import_id": imp_id, "id": {"$ne": f"btx_{MARK}_c04b"}}))
        assert all(t["status"] == "duplicate" for t in twins), twins


# ---------------------------------------------------------------------------
# CB05 — reversión segura y reanudable
# ---------------------------------------------------------------------------
class TestCB05Rollback:
    def test_completed_order_blocks_rollback_without_releasing_tx(self):
        """Variante A: la orden avanzó a completed — el rollback bloquea y el
        movimiento bancario NO se libera."""
        db = _db()
        oid = f"ord{MARK}c05a"
        tx = _mk_tx(f"btx_{MARK}_c05a", 100.0, status="manual_matched",
                    matched_order_id=oid, matched_kind="order")
        _mk_order(oid, 100, "ANA PEREZ", status="completed")
        db.orders.update_one({"id": oid}, {"$set": {
            "reconciliation": {"bank_transaction_id": tx["id"]}}})
        r = requests.post(f"{API}/transactions/{tx['id']}/rollback",
                          headers=_h(ADMIN), json={"reason": "prueba CB05 A"})
        assert r.status_code == 409, r.text
        fresh = db.bank_transactions.find_one({"id": tx["id"]})
        assert fresh["status"] == "manual_matched", \
            "un fallo de estado nunca libera el respaldo bancario"
        assert fresh["matched_order_id"] == oid

    def test_interrupted_rollback_resumes_bank_close(self):
        """Variante B: la orden ya fue revertida (marcador) pero el cierre del
        movimiento quedó pendiente — el reintento finaliza sin 409 ni doble
        débito."""
        db = _db()
        oid = f"ord{MARK}c05b"
        tx = _mk_tx(f"btx_{MARK}_c05b", 100.0, status="manual_matched",
                    matched_order_id=oid, matched_kind="order")
        _mk_order(oid, 100, "ANA PEREZ", status="pending")
        db.orders.update_one({"id": oid}, {"$set": {
            "last_recon_rollback": {"tx_id": tx["id"], "at": _now()}}})
        r = requests.post(f"{API}/transactions/{tx['id']}/rollback",
                          headers=_h(ADMIN), json={"reason": "reanudar cierre"})
        assert r.status_code == 200, r.text
        fresh = db.bank_transactions.find_one({"id": tx["id"]})
        assert fresh["status"] in ("unmatched", "manual_review")
        assert fresh["matched_order_id"] is None
        assert db.orders.find_one({"id": oid})["status"] == "pending"

    def test_normal_rollback_still_works(self):
        db = _db()
        oid = f"ord{MARK}c05c"
        _mk_order(oid, 100, "ANA PEREZ")
        tx = _mk_tx(f"btx_{MARK}_c05c", 100.0)
        r = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                          headers=_h(ADMIN), json={"order_id": oid})
        assert r.status_code == 200, r.text
        r2 = requests.post(f"{API}/transactions/{tx['id']}/rollback",
                           headers=_h(ADMIN), json={"reason": "control positivo"})
        assert r2.status_code == 200, r2.text
        assert db.orders.find_one({"id": oid})["status"] == "pending"
