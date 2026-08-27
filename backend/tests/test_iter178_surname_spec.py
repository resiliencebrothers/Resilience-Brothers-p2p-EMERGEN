"""iter178 — Spec V2 Apellidos (archivo subido por el usuario).

  - Apellido OBLIGATORIO para auto-match: similitud ≥ surname_match_threshold
    (default 0.75) o el movimiento va a revisión con surname_mismatch.
  - Iniciales: JOSE M PEREZ GARCIA ≡ JOSE MANUEL PEREZ GARCIA.
  - Misma combinación nombre+monto+fecha en LOTES distintos → nunca auto
    (duplicate_across_batches), mostrando todas las candidatas.
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

PACC_ID = "pacc_test178"
API = f"{BASE_URL}/api/admin/reconciliation"
VIP_ID = "user_test_vip01"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _upload(csv_text, filename):
    return requests.post(
        f"{API}/imports", headers=_h(ADMIN),
        files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
        data={"bank_account_id": PACC_ID, "bank_name": "Wells Fargo",
              "currency": "USD"})


def _wait_processed(import_id, timeout=45):
    for _ in range(timeout):
        r = requests.get(f"{API}/imports/{import_id}", headers=_h(ADMIN))
        doc = r.json()
        if doc["processing_status"] not in ("uploaded", "processing"):
            return doc
        time.sleep(1)
    raise TimeoutError("import never finished")


def _mk_order(db, order_id, amount, name):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.orders.insert_one({
        "id": order_id, "user_id": "user_test_normal01",
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": name, "payment_reference": "",
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": "USD", "to_code": "CUP", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 178",
        "created_at": now, "updated_at": now,
    })


def _mk_batch(db):
    batch_id = f"vbatch_t178_{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.vip_batches.insert_one({
        "id": batch_id, "vip_user_id": VIP_ID, "vip_email": "vip.test@resilience.com",
        "vip_name": "VIP Test", "direction": "pair", "currency": "USD",
        "from_code": "USD", "to_code": "USDT", "rate_vip": 0.95,
        "requires_card": False, "note": None, "status": "open",
        "items_pending": 0, "items_approved": 0, "items_rejected": 0,
        "amount_pending": 0.0, "amount_approved": 0.0,
        "created_at": now, "updated_at": now, "closed_at": None,
    })
    return batch_id


def _mk_item(db, batch_id, holder, amount):
    item_id = f"vitem_t178_{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.vip_batch_items.insert_one({
        "id": item_id, "batch_id": batch_id, "vip_user_id": VIP_ID,
        "holder_name": holder, "card_number": None,
        "amount": float(amount), "currency": "USD", "direction": "pair",
        "from_code": "USD", "to_code": "USDT",
        "rate_applied": 0.95, "amount_to": round(float(amount) * 0.95, 4),
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 178",
        "payment_reference": "",
        "status": "pending", "admin_note": None, "balance_delta_usdt": None,
        "margin_usdt": None, "created_at": now, "updated_at": now,
        "reviewed_at": None, "reviewed_by": None,
    })
    return item_id


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test178_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord178"}})
    db.vip_batch_items.delete_many({"id": {"$regex": "^vitem_t178_"}})
    db.vip_batches.delete_many({"id": {"$regex": "^vbatch_t178_"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestNormalizationAndInitials:
    def test_reordered_full_name_is_equivalent(self):
        from services.reconciliation_matcher import name_similarity
        assert name_similarity("PEREZ GARCIA JOSE MANUEL",
                               "Jose Manuel Perez Garcia") >= 0.95

    def test_initials_are_equivalent(self):
        from services.reconciliation_matcher import name_similarity
        assert name_similarity("JOSE M PEREZ GARCIA",
                               "Jose Manuel Perez Garcia") >= 0.95

    def test_punctuation_and_double_spaces(self):
        from services.reconciliation_matcher import name_similarity
        assert name_similarity("PEREZ, GARCIA.  JOSE  MANUEL",
                               "José Manuel Pérez García") >= 0.95


class TestSurnameSimilarity:
    def test_ocr_typos_pass_threshold(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("OSCAR GONSALES", "Oscar Gonzalez") >= 0.75
        assert surname_similarity("MARIA LOPES", "Maria Lopez") >= 0.75

    def test_different_surname_fails(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("JUAN PEREZ", "Juan Gomez") < 0.75

    def test_first_name_only_fails(self):
        from services.reconciliation_matcher import surname_similarity
        assert surname_similarity("YUNIESKI", "Yunieski Batista Ferrer") < 0.75

    def test_score_pair_gates_surname_bonus(self):
        from services.reconciliation_matcher import score_pair, DEFAULT_CONFIG
        today = time.strftime("%Y-%m-%d")
        s = score_pair(
            {"amount": 100.0, "sender_name": "YUNIESKI",
             "transaction_date": today},
            {"amount_from": 100.0, "sender_name": "Yunieski Batista Ferrer",
             "user_name": "", "created_at": today}, dict(DEFAULT_CONFIG))
        assert s["breakdown"]["surname_score"] == 0
        assert s["breakdown"]["surname_similarity"] < 0.75


class TestSurnameMandatoryE2E:
    def setup_method(self):
        _cleanup()

    def test_first_name_only_never_auto(self):
        """Nombre de pila + monto exacto + mismo día = 102 pts, pero sin
        apellido → NUNCA auto (spec: REGLA DE SEGURIDAD)."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        oid = f"ord178a_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 415.77, "Yunieski Batista Ferrer")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Zelle payment,415.77,YUNIESKI\n")
        imp = _wait_processed(_upload(
            csv_text, f"test178_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 0, imp
        assert imp["total_manual_review"] == 1, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "manual_review"
        assert "surname_mismatch" in tx["auto_block_reasons"]
        assert tx["review_flag"] == "surname_mismatch"
        assert db.orders.find_one({"id": oid})["status"] == "pending"

    def test_initials_auto_confirm(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        oid = f"ord178b_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 528.43, "Jose Manuel Perez Garcia")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Zelle payment,528.43,JOSE M PEREZ GARCIA\n")
        imp = _wait_processed(_upload(
            csv_text, f"test178_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        assert db.orders.find_one({"id": oid})["status"] == "approved"

    def test_ocr_surname_typo_still_auto(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        oid = f"ord178c_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 611.29, "Oscar Deivi Gonzalez")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Zelle payment,611.29,OSCAR DEIVI GONSALES\n")
        imp = _wait_processed(_upload(
            csv_text, f"test178_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        assert db.orders.find_one({"id": oid})["status"] == "approved"


class TestDuplicateAcrossBatches:
    def setup_method(self):
        _cleanup()

    def test_same_combo_in_two_batches_goes_to_review(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        b1, b2 = _mk_batch(db), _mk_batch(db)
        i1 = _mk_item(db, b1, "Dayami Rosales Pino", 233.19)
        i2 = _mk_item(db, b2, "Dayami Rosales Pino", 233.19)
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia recibida,233.19,DAYAMI ROSALES PINO\n")
        imp = _wait_processed(_upload(
            csv_text, f"test178_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 0, imp
        assert imp["total_manual_review"] == 1, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert "duplicate_across_batches" in tx["auto_block_reasons"]
        assert len(tx["candidates"]) >= 2  # spec: mostrar todas las candidatas
        for iid in (i1, i2):
            assert db.vip_batch_items.find_one({"id": iid})["status"] == "pending"


class TestSurnameThresholdConfig:
    def test_update_and_validation(self):
        r = requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"surname_match_threshold": 0.9})
        assert r.status_code == 200, r.text
        assert r.json()["surname_match_threshold"] == 0.9
        r_bad = requests.put(f"{API}/config", headers=_h(ADMIN),
                             json={"surname_match_threshold": 1.5})
        assert r_bad.status_code == 422
        requests.put(f"{API}/config", headers=_h(ADMIN),
                     json={"surname_match_threshold": 0.75})
