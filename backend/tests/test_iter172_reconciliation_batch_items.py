"""iter172 — Conciliación bancaria: ítems de Lotes VIP como candidatos.

Root causes fixed (reporte de producción, jun 2026):
  1. vip_batch_items nunca eran candidatos → los lotes jamás se conciliaban.
  2. auto_match_score=95 era inalcanzable sin referencia bancaria → nada se
     auto-confirmaba (match perfecto = 90). Default bajado a 90.
  3. Monto exacto + nombre sin coincidencia caía en "sin identificar" (65<80)
     → ahora va a revisión manual con flag name_mismatch.
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

PACC_ID = "pacc_test172"
API = f"{BASE_URL}/api/admin/reconciliation"
VIP_ID = "user_test_vip01"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mk_batch(db):
    batch_id = f"vbatch_t172_{uuid.uuid4().hex[:8]}"
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


def _mk_item(db, batch_id, holder, amount, created_at=None):
    item_id = f"vitem_t172_{uuid.uuid4().hex[:8]}"
    now = created_at or time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.vip_batch_items.insert_one({
        "id": item_id, "batch_id": batch_id, "vip_user_id": VIP_ID,
        "holder_name": holder, "card_number": None,
        "amount": float(amount), "currency": "USD", "direction": "pair",
        "from_code": "USD", "to_code": "USDT",
        "rate_applied": 0.95, "amount_to": round(float(amount) * 0.95, 4),
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 172",
        "status": "pending", "admin_note": None, "balance_delta_usdt": None,
        "margin_usdt": None, "created_at": now, "updated_at": now,
        "reviewed_at": None, "reviewed_by": None,
    })
    return item_id


def _mk_order(db, order_id, amount, name):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.orders.insert_one({
        "id": order_id, "user_id": "user_test_normal01",
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": name,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": "USD", "to_code": "CUP", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 172",
        "created_at": now, "updated_at": now,
    })


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


def _vip_usdt_balance(db):
    u = db.users.find_one({"user_id": VIP_ID}, {"vip_balances": 1}) or {}
    return float((u.get("vip_balances") or {}).get("USDT") or 0.0)


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test172_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord172"}})
    db.vip_batch_items.delete_many({"id": {"$regex": "^vitem_t172_"}})
    db.vip_batches.delete_many({"id": {"$regex": "^vbatch_t172_"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestBatchItemAutoMatch:
    def test_exact_holder_auto_matched(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        batch_id = _mk_batch(db)
        item_id = _mk_item(db, batch_id, "Emilia Rivero Munoz", 300.00)
        balance_before = _vip_usdt_balance(db)

        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia recibida,300.00,EMILIA RIVERO MUNOZ\n")
        r = _upload(csv_text, f"test172_{uuid.uuid4().hex[:6]}.csv")
        assert r.status_code == 200, r.text
        imp = _wait_processed(r.json()["id"])
        assert imp["total_auto_matched"] == 1, imp

        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "auto_matched"
        assert tx["matched_order_id"] == item_id
        assert tx["matched_kind"] == "vip_batch_item"
        # score 90 = 45 monto + 10 moneda + 25 nombre exacto + 10 mismo día
        assert tx["confidence_score"] >= 90

        item = db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
        assert item["status"] == "approved"
        assert item["payment_confirmation_source"] == "BANK_RECONCILIATION"
        assert item["reconciliation"]["auto"] is True
        assert item["reconciliation"]["bank_transaction_id"] == tx["id"]

        # amount_to credited to VIP balance (300 * 0.95 = 285 USDT)
        assert abs(_vip_usdt_balance(db) - balance_before - 285.0) < 0.01

        batch = db.vip_batches.find_one({"id": batch_id}, {"_id": 0})
        assert batch["items_approved"] == 1 and batch["items_pending"] == 0

    def test_typo_name_goes_to_review_not_auto(self):
        # V2 (iter177): typo leve (≥95%) ahora SÍ auto-confirma; este test
        # cubre el typo FUERTE (<80%) que debe quedar en revisión humana.
        db = _db()
        today = time.strftime("%Y-%m-%d")
        batch_id = _mk_batch(db)
        item_id = _mk_item(db, batch_id, "Oscar Deivi Gonzalez", 50.00)

        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia recibida,50.00,OSKAR D GONSALES\n")
        imp = _wait_processed(_upload(
            csv_text, f"test172_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_manual_review"] == 1, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "manual_review"
        assert tx["candidates"][0]["order_id"] == item_id
        assert tx["candidates"][0]["kind"] == "vip_batch_item"
        assert db.vip_batch_items.find_one({"id": item_id})["status"] == "pending"

    def test_duplicate_name_same_amount_ambiguity_review(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        batch_id = _mk_batch(db)
        i1 = _mk_item(db, batch_id, "Jose Luis Perez", 200.00)
        i2 = _mk_item(db, batch_id, "Jose Luis Perez", 200.00)

        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia recibida,200.00,JOSE LUIS PEREZ\n")
        imp = _wait_processed(_upload(
            csv_text, f"test172_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 0, imp
        assert imp["total_manual_review"] == 1, imp
        for iid in (i1, i2):
            assert db.vip_batch_items.find_one({"id": iid})["status"] == "pending"

    def test_wrong_name_exact_amount_flagged_for_review(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        batch_id = _mk_batch(db)
        _mk_item(db, batch_id, "Maria Perez Soto", 75.00)

        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia recibida,75.00,TOTALLY DIFFERENT PERSON\n")
        imp = _wait_processed(_upload(
            csv_text, f"test172_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_manual_review"] == 1, imp
        assert imp["total_unmatched"] == 0, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "manual_review"
        assert tx["review_flag"] == "name_mismatch"


class TestBatchItemManualFlow:
    def test_manual_confirm_and_rollback(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        batch_id = _mk_batch(db)
        item_id = _mk_item(db, batch_id, "Damaris Julien Rodriguez", 120.00)
        balance_before = _vip_usdt_balance(db)

        # V2: "D JULIEN" ya auto-concilia por iniciales+apellido; usamos un
        # nombre distinto para ejercitar el flujo manual (safety-net review).
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},SEPA Instant,120.00,MARTA QUESADA LEON\n")
        imp = _wait_processed(_upload(
            csv_text, f"test172_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] in ("manual_review", "unmatched")

        # búsqueda del picker incluye ítems de lote
        rs = requests.get(f"{API}/orders-search", headers=_h(ADMIN),
                          params={"currency": "USD", "q": "Damaris"})
        assert rs.status_code == 200
        found = [x for x in rs.json()["items"] if x["id"] == item_id]
        assert found and found[0]["kind"] == "vip_batch_item"

        rc = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                           headers=_h(ADMIN), json={"order_id": item_id})
        assert rc.status_code == 200, rc.text
        assert rc.json()["status"] == "manual_matched"
        assert rc.json()["matched_kind"] == "vip_batch_item"
        item = db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
        assert item["status"] == "approved"
        assert abs(_vip_usdt_balance(db) - balance_before - 114.0) < 0.01

        # double-confirm guard
        rc2 = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                            headers=_h(ADMIN), json={"order_id": item_id})
        assert rc2.status_code == 409

        # rollback revierte saldo + vuelve a pendiente
        rb = requests.post(f"{API}/transactions/{tx['id']}/rollback",
                           headers=_h(ADMIN), json={"reason": "monto en disputa"})
        assert rb.status_code == 200, rb.text
        item = db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
        assert item["status"] == "pending"
        assert "reconciliation" not in item
        assert abs(_vip_usdt_balance(db) - balance_before) < 0.01
        batch = db.vip_batches.find_one({"id": batch_id}, {"_id": 0})
        assert batch["items_pending"] == 1 and batch["items_approved"] == 0


class TestOrderAutoMatchWithoutReference:
    def test_perfect_match_no_reference_auto_confirms(self):
        """Fix núcleo del reporte: match perfecto (monto+nombre+fecha) debe
        auto-confirmar aunque el banco no incluya referencia (score 90)."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        oid = f"ord172_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 440.00, "Carlos Ruiz Ferrer")

        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Zelle payment received,440.00,CARLOS RUIZ FERRER\n")
        imp = _wait_processed(_upload(
            csv_text, f"test172_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        order = db.orders.find_one({"id": oid}, {"_id": 0})
        assert order["status"] == "approved"
        assert order["payment_confirmation_source"] == "BANK_RECONCILIATION"
