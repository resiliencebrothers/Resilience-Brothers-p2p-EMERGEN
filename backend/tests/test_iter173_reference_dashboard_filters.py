"""iter173 — §61 referencia RB-XXXXXX, §38/§52 dashboard, §40 filtros.

- payment_reference generada en órdenes y en ítems de lote; +20 pts si aparece
  en el concepto/referencia del extracto → auto-match casi garantizado.
- GET /admin/reconciliation/dashboard — métricas operativas.
- GET /admin/reconciliation/transactions — filtros q/fecha/monto/score.
"""
import io
import sys
import time
import uuid

import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from conftest import BASE_URL, ADMIN_TOKEN as ADMIN  # noqa: E402

import os  # noqa: E402

PACC_ID = "pacc_test173"
API = f"{BASE_URL}/api/admin/reconciliation"
VIP_ID = "user_test_vip01"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mk_batch(db):
    batch_id = f"vbatch_t173_{uuid.uuid4().hex[:8]}"
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


def _mk_item(db, batch_id, holder, amount, ref):
    item_id = f"vitem_t173_{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.vip_batch_items.insert_one({
        "id": item_id, "batch_id": batch_id, "vip_user_id": VIP_ID,
        "holder_name": holder, "card_number": None,
        "amount": float(amount), "currency": "USD", "direction": "pair",
        "from_code": "USD", "to_code": "USDT",
        "rate_applied": 0.95, "amount_to": round(float(amount) * 0.95, 4),
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 173",
        "payment_reference": ref,
        "status": "pending", "admin_note": None, "balance_delta_usdt": None,
        "margin_usdt": None, "created_at": now, "updated_at": now,
        "reviewed_at": None, "reviewed_by": None,
    })
    return item_id


def _mk_order(db, order_id, amount, name, ref):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.orders.insert_one({
        "id": order_id, "user_id": "user_test_normal01",
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": name, "payment_reference": ref,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": "USD", "to_code": "CUP", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 173",
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


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test173_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord173"}})
    db.vip_batch_items.delete_many({"id": {"$regex": "^vitem_t173_"}})
    db.vip_batches.delete_many({"id": {"$regex": "^vbatch_t173_"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestPaymentReference:
    def test_generator_format(self):
        from services.payment_reference import generate_payment_reference
        refs = {generate_payment_reference() for _ in range(50)}
        assert all(r.startswith("RB-") and len(r) == 9 and r[3:].isdigit()
                   for r in refs)
        assert len(refs) > 45

    def test_order_model_autogenerates_reference(self):
        from services.orders_helpers import Order
        factory = Order.model_fields["payment_reference"].default_factory
        assert factory is not None
        assert factory().startswith("RB-")

    def test_reference_in_concept_boosts_to_auto(self):
        """Nombre con typo fuerte (0 pts) + monto exacto + fecha = 65.
        Con la referencia RB en el concepto → 85… no: 65+20=85 <90 review.
        Caso spec: typo leve (23) + ref (20) → 108 → AUTO garantizado."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        ref = "RB-731942"
        oid = f"ord173_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 620.00, "Yasmany Gutierrez Lopez", ref)

        csv_text = ("Date,Description,Amount,Sender,Reference\n"
                    f"{today},Pago {ref},620.00,YASMANI GUTIERREZ LOPEZ,{ref}\n")
        imp = _wait_processed(_upload(
            csv_text, f"test173_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "auto_matched"
        assert tx["match_details"]["breakdown"]["reference_score"] == 20
        assert db.orders.find_one({"id": oid})["status"] == "approved"

    def test_batch_item_reference_match(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        ref = "RB-556677"
        batch_id = _mk_batch(db)
        item_id = _mk_item(db, batch_id, "Caridad Fonseca Diaz", 90.00, ref)

        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia concepto {ref},90.00,CARIDAD FONSECA DIAZ\n")
        imp = _wait_processed(_upload(
            csv_text, f"test173_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        item = db.vip_batch_items.find_one({"id": item_id}, {"_id": 0})
        assert item["status"] == "approved"
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["match_details"]["breakdown"]["reference_score"] == 20
        # score 110 (45+10+25+10+20) — persiste raw, la UI lo capa a 100
        assert tx["confidence_score"] >= 100


class TestDashboard:
    def test_dashboard_shape_and_counts(self):
        r = requests.get(f"{API}/dashboard", headers=_h(ADMIN),
                         params={"days": 30})
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("window_days", "today", "counts", "auto_match_rate",
                    "manual_review_rate", "unmatched_rate", "avg_score_matched",
                    "avg_processing_seconds", "ocr_usage_rate",
                    "parser_error_rate", "rollbacks", "reconciled_by_currency",
                    "reconciled", "imports_window"):
            assert key in d, key
        assert d["window_days"] == 30
        assert d["counts"].get("auto_matched", 0) >= 2  # de los tests previos
        assert any(c["currency"] == "USD" for c in d["reconciled_by_currency"])

    def test_dashboard_requires_permission(self):
        r = requests.get(f"{API}/dashboard")
        assert r.status_code in (401, 403)


class TestTransactionFilters:
    def test_filters(self):
        base = {"status": None}
        # sanity: los movimientos de los tests previos existen
        r_all = requests.get(f"{API}/transactions", headers=_h(ADMIN),
                             params={"limit": 500})
        assert r_all.status_code == 200
        ids = {t["id"] for t in r_all.json()["items"]}
        assert ids, "no transactions to filter"

        r_q = requests.get(f"{API}/transactions", headers=_h(ADMIN),
                           params={"q": "CARIDAD FONSECA"})
        names = {t.get("sender_name") for t in r_q.json()["items"]}
        assert names and all("CARIDAD" in (n or "").upper() for n in names)

        r_amt = requests.get(f"{API}/transactions", headers=_h(ADMIN),
                             params={"amount_min": 600, "amount_max": 700})
        amounts = [t["amount"] for t in r_amt.json()["items"]]
        assert amounts and all(600 <= a <= 700 for a in amounts)

        r_score = requests.get(f"{API}/transactions", headers=_h(ADMIN),
                               params={"score_min": 100})
        assert all((t.get("confidence_score") or 0) >= 100
                   for t in r_score.json()["items"])

        today = time.strftime("%Y-%m-%d")
        r_date = requests.get(f"{API}/transactions", headers=_h(ADMIN),
                              params={"date_from": today, "date_to": today})
        assert all(str(t["transaction_date"])[:10] == today
                   for t in r_date.json()["items"])
        assert base["status"] is None
