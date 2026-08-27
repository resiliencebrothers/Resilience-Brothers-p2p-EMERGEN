"""iter186 — Statement import diagnostics.

1. A PDF whose text yields no rows falls back to file-attachment OCR.
2. An import that produces 0 movements is marked FAILED with a clear note.
3. An import where all movements are debits keeps a warning note.
4. Currency pills include import currencies even with 0 movements.
"""
import asyncio
import os
import time
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _upload_csv(content: str, currency: str, bank: str = "TestBank"):
    files = {"file": (f"stmt_{uuid.uuid4().hex[:6]}.csv", content.encode(), "text/csv")}
    data = {"bank_account_id": "", "bank_name": bank, "currency": currency}
    r = requests.post(f"{API}/admin/reconciliation/imports", headers=_hdr(ADMIN_TOKEN),
                      files=files, data=data)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _wait_processed(import_id: str, timeout: float = 25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{API}/admin/reconciliation/imports/{import_id}",
                         headers=_hdr(ADMIN_TOKEN))
        d = r.json()
        if d.get("processing_status") not in ("uploaded", "processing"):
            return d
        time.sleep(1)
    raise AssertionError("import did not finish processing in time")


def _cleanup(currency: str):
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"currency": currency}, {"_id": 0, "id": 1})]
    db.bank_statement_imports.delete_many({"currency": currency})
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})


def test_pdf_ocr_fallback_when_text_yields_no_rows(monkeypatch):
    import fitz
    import services.reconciliation_parser as rp

    doc = fitz.open()
    page = doc.new_page()
    for i in range(8):
        page.insert_text((72, 72 + i * 14), f"RESILIENCE BROTHERS statement header line {i}")
    pdf_bytes = doc.tobytes()

    calls = {"text": 0, "ocr": 0}

    async def fake_text(_text):
        calls["text"] += 1
        return []

    async def fake_ocr(_path):
        calls["ocr"] += 1
        return [{"transaction_date": "2099-02-01", "time": None, "amount": 120.5,
                 "direction": "credit", "sender_name": "Juan Perez",
                 "beneficiary_name": None, "description": "Zelle payment",
                 "reference": "Z1", "balance_after": None,
                 "payment_method": "Zelle", "raw": {"source": "llm"}}]

    monkeypatch.setattr(rp, "llm_extract_from_text", fake_text)
    monkeypatch.setattr(rp, "llm_extract_from_pdf", fake_ocr)
    txs, errors, mode = asyncio.run(rp.parse_statement(pdf_bytes, "pdf", dayfirst=False))
    assert calls == {"text": 1, "ocr": 1}
    assert mode == "pdf_ocr_llm"
    assert len(txs) == 1 and txs[0]["amount"] == 120.5


def test_zero_movements_import_marked_failed_with_note():
    cur = "ZL186"
    _cleanup(cur)
    try:
        iid = _upload_csv(f"Date,Amount,Description,U{uuid.uuid4().hex[:8]}\n", cur)
        d = _wait_processed(iid)
        assert d["processing_status"] == "failed", d
        assert "No se detectó ningún movimiento" in (d.get("notes") or "")
        assert d["total_transactions_detected"] == 0
    finally:
        _cleanup(cur)


def test_all_debits_import_keeps_warning_note():
    cur = "ZD186"
    _cleanup(cur)
    try:
        csv = (f"Date,Amount,Description,Name,U{uuid.uuid4().hex[:8]}\n"
               "2099-02-05,-100.00,Zelle payment sent,Juan Perez,x\n"
               "2099-02-06,-50.00,Zelle payment sent,Ana Ruiz,x\n")
        iid = _upload_csv(csv, cur)
        d = _wait_processed(iid)
        assert d["processing_status"] == "processed", d
        assert "egresos" in (d.get("notes") or ""), d.get("notes")
        assert d["total_transactions_detected"] == 2
        assert d["total_credits_detected"] == 0
        statuses = {t["status"] for t in _db().bank_transactions.find(
            {"statement_import_id": iid}, {"_id": 0, "status": 1})}
        assert statuses == {"ignored"}
    finally:
        _cleanup(cur)


def test_summary_currencies_include_import_only_currency():
    cur = "ZL186B"
    _cleanup(cur)
    try:
        iid = _upload_csv(f"Date,Amount,Description,U{uuid.uuid4().hex[:8]}\n", cur)
        _wait_processed(iid)  # fails → creates NO transactions
        r = requests.get(f"{API}/admin/reconciliation/summary", headers=_hdr(ADMIN_TOKEN))
        assert cur in r.json()["currencies"], r.json()["currencies"]
    finally:
        _cleanup(cur)
