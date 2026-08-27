"""iter188 — Reprocess an already-uploaded statement without re-uploading.

- POST /admin/reconciliation/imports/{id}/reprocess re-runs parse + matching
  from the stored file.
- Matched movements are preserved; non-matched ones are re-created.
- 404 unknown import; 410 when the stored file is gone.
"""
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


def _upload_csv(content: str, currency: str):
    files = {"file": (f"stmt_{uuid.uuid4().hex[:6]}.csv", content.encode(), "text/csv")}
    data = {"bank_account_id": "", "bank_name": "TestBank", "currency": currency}
    r = requests.post(f"{API}/admin/reconciliation/imports", headers=_hdr(ADMIN_TOKEN),
                      files=files, data=data)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _wait(import_id: str, timeout: float = 25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = requests.get(f"{API}/admin/reconciliation/imports/{import_id}",
                         headers=_hdr(ADMIN_TOKEN)).json()
        if d.get("processing_status") not in ("uploaded", "processing"):
            return d
        time.sleep(1)
    raise AssertionError("import did not finish in time")


def _cleanup(currency: str):
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"currency": currency}, {"_id": 0, "id": 1})]
    db.bank_statement_imports.delete_many({"currency": currency})
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})


def test_reprocess_reruns_pipeline_and_preserves_matched():
    cur = "RP188"
    _cleanup(cur)
    try:
        csv = (f"Date,Amount,Description,Name,U{uuid.uuid4().hex[:8]}\n"
               "2099-04-01,100.00,Zelle payment,Juan Perez,x\n"
               "2099-04-02,55.00,Zelle payment,Ana Ruiz,x\n")
        iid = _upload_csv(csv, cur)
        d = _wait(iid)
        assert d["processing_status"] == "processed"
        assert d["total_transactions_detected"] == 2

        # simulate one movement already matched
        db = _db()
        tx = db.bank_transactions.find_one({"statement_import_id": iid})
        db.bank_transactions.update_one(
            {"id": tx["id"]}, {"$set": {"status": "manual_matched",
                                        "matched_order_id": "ord_fake_188"}})

        r = requests.post(f"{API}/admin/reconciliation/imports/{iid}/reprocess",
                          headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        assert r.json()["removed_unmatched"] == 1

        d2 = _wait(iid)
        assert d2["processing_status"] == "processed"
        txs = list(db.bank_transactions.find({"statement_import_id": iid}, {"_id": 0}))
        matched = [t for t in txs if t["status"] == "manual_matched"]
        assert len(matched) == 1 and matched[0]["id"] == tx["id"]
        # the re-parsed row identical to the kept match dedupes as duplicate
        assert any(t["status"] == "duplicate" for t in txs)
    finally:
        _cleanup(cur)


def test_reprocess_unknown_import_404():
    r = requests.post(f"{API}/admin/reconciliation/imports/imp_nope188/reprocess",
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 404


def test_reprocess_missing_file_410():
    cur = "RP188B"
    _cleanup(cur)
    try:
        iid = _upload_csv(f"Date,Amount,U{uuid.uuid4().hex[:8]}\n2099-04-03,10.00,x\n", cur)
        _wait(iid)
        _db().statement_files.delete_many({"id": iid})
        _db().bank_statement_imports.update_one(
            {"id": iid}, {"$set": {"stored_file_url": f"mongo://{iid}"}})
        r = requests.post(f"{API}/admin/reconciliation/imports/{iid}/reprocess",
                          headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 410, r.text
    finally:
        _cleanup(cur)
