"""iter148 — VIP batch massive-inflow threshold alerts + wallet destination.

Covers:
1. Pure logic `evaluate_threshold_events`: big-item at/below threshold, batch
   cumulative crossing, double-based re-fire dedup, debit skipped, approved
   stage uses only amount_approved.
2. HTTP E2E: VIP adds a big item → wallet (payment_account_details) is
   snapshotted on the item AND the cumulative-alert marker is written on the
   batch; a tiny follow-up add does NOT re-fire; admin approval writes the
   approved-stage marker.
"""
import os

import pytest
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN
from services.vip_batch_alerts import evaluate_threshold_events, TOTAL_MARKER

API = f"{BASE_URL}/api"

FROM_CODE = "ZBT"    # synthetic source currency (1 ZBT = 1 USDT via test rate)
TO_CODE = "CPT8"     # synthetic destination currency
WALLET = "TRC20: TXtestWallet9912abcDEF"
ACC_LABEL = "Binance TRC20 Principal (test)"

STATE: dict = {}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _threshold(db):
    s = db.settings.find_one({"id": "global"}) or {}
    return float(s.get("vip_threshold_usdt", 5000))


@pytest.fixture(scope="module", autouse=True)
def _seed_world():
    db = _db()
    db.currencies.update_one({"code": FROM_CODE}, {"$set": {
        "id": "test_cur_zbt", "code": FROM_CODE, "name": "Zeta Batch Test",
        "type": "fiat", "symbol": "$", "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.currencies.update_one({"code": TO_CODE}, {"$set": {
        "id": "test_cur_cpt8", "code": TO_CODE, "name": "Peso Test Ocho",
        "type": "fiat", "symbol": "₱", "is_active": True, "payment_account": "",
        "delivery_methods": ["transfer"],
    }}, upsert=True)
    db.rates.update_one({"from_code": FROM_CODE, "to_code": TO_CODE}, {"$set": {
        "id": "test_rate_zbt_cpt8", "from_code": FROM_CODE, "to_code": TO_CODE,
        "rate_normal": 90, "rate_vip": 100, "real_rate": 110,
    }}, upsert=True)
    # valuation path so convert_to_usdt(ZBT) = 1:1 (rate_vip=0 keeps it out of batch pairs)
    db.rates.update_one({"from_code": "USDT", "to_code": FROM_CODE}, {"$set": {
        "id": "test_rate_usdt_zbt", "from_code": "USDT", "to_code": FROM_CODE,
        "rate_normal": 1.0, "rate_vip": 0,
    }}, upsert=True)
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    db.payment_accounts.insert_one({
        "id": "payacc_test_zbt", "currency_code": FROM_CODE,
        "label": ACC_LABEL, "account_details": WALLET,
        "min_amount": 10, "max_amount": None, "is_active": True,
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:00:00+00:00",
    })
    yield
    db.payment_accounts.delete_many({"currency_code": FROM_CODE})
    db.currencies.delete_many({"code": {"$in": [FROM_CODE, TO_CODE]}})
    db.rates.delete_many({"id": {"$in": ["test_rate_zbt_cpt8", "test_rate_usdt_zbt"]}})
    db.vip_batch_items.delete_many({"from_code": FROM_CODE})
    db.vip_batches.delete_many({"currency": FROM_CODE})
    db.notifications.delete_many({"type": "vip_batch_threshold"})


# ------------------------------------------------------------------
# 1. Pure logic
# ------------------------------------------------------------------

RATES = {("USDT", "ZBT"): 1.0}


def _mk_batch(**over):
    b = {"id": "vb_test", "direction": "pair", "from_code": "ZBT",
         "to_code": "CPT8", "currency": "ZBT",
         "amount_pending": 0.0, "amount_approved": 0.0,
         "vip_name": "Vip Test"}
    b.update(over)
    return b


def test_big_item_fires_at_exact_threshold():
    evs = evaluate_threshold_events(
        _mk_batch(amount_pending=5000),
        [{"amount": 5000, "payment_account_label": "W1"}],
        5000, RATES, "added")
    kinds = [e["kind"] for e in evs]
    assert "big_item" in kinds and "batch_total" in kinds
    big = next(e for e in evs if e["kind"] == "big_item")
    assert big["max_usdt"] == 5000
    assert big["labels"] == ["W1"]


def test_below_threshold_no_events():
    evs = evaluate_threshold_events(
        _mk_batch(amount_pending=4999),
        [{"amount": 4999}], 5000, RATES, "added")
    assert evs == []


def test_total_crossing_without_big_item():
    evs = evaluate_threshold_events(
        _mk_batch(amount_pending=5200),
        [{"amount": 300}], 5000, RATES, "added")
    assert [e["kind"] for e in evs] == ["batch_total"]
    assert evs[0]["total_usdt"] == 5200


def test_total_refire_requires_double():
    # last alert at 6000 → 6010 does NOT re-fire, 12000 does
    evs = evaluate_threshold_events(
        _mk_batch(amount_pending=6010, last_alert_total_usdt=6000),
        [{"amount": 10}], 5000, RATES, "added")
    assert evs == []
    evs2 = evaluate_threshold_events(
        _mk_batch(amount_pending=12000, last_alert_total_usdt=6000),
        [{"amount": 10}], 5000, RATES, "added")
    assert [e["kind"] for e in evs2] == ["batch_total"]


def test_debit_batch_skipped():
    evs = evaluate_threshold_events(
        _mk_batch(direction="debit", amount_pending=999999),
        [{"amount": 999999}], 5000, RATES, "added")
    assert evs == []


def test_approved_stage_uses_only_approved_total():
    evs = evaluate_threshold_events(
        _mk_batch(amount_pending=999999, amount_approved=100),
        [{"amount": 100}], 5000, RATES, "approved")
    assert evs == []
    evs2 = evaluate_threshold_events(
        _mk_batch(amount_pending=0, amount_approved=7000),
        [{"amount": 100}], 5000, RATES, "approved")
    assert [e["kind"] for e in evs2] == ["batch_total"]
    assert evs2[0]["total_usdt"] == 7000


def test_no_conversion_path_no_events():
    evs = evaluate_threshold_events(
        _mk_batch(from_code="XXNOPE", currency="XXNOPE", amount_pending=1e9),
        [{"amount": 1e9}], 5000, {}, "added")
    assert evs == []


# ------------------------------------------------------------------
# 2. HTTP E2E — add big item → wallet snapshot + alert markers
# ------------------------------------------------------------------

def test_e2e_create_batch():
    r = requests.post(f"{API}/vip/batches", headers=_hdr(VIP_TOKEN),
                      json={"from_code": FROM_CODE, "to_code": TO_CODE})
    assert r.status_code == 200, r.text
    STATE["batch_id"] = r.json()["id"]


def test_e2e_big_item_snapshots_wallet_and_marks_alert():
    db = _db()
    threshold = _threshold(db)
    big = round(threshold * 1.2, 2)
    r = requests.post(
        f"{API}/vip/batches/{STATE['batch_id']}/items", headers=_hdr(VIP_TOKEN),
        json={"items": [{"holder_name": "Juan Masivo", "amount": big}]})
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["payment_account_label"] == ACC_LABEL
    assert item["payment_account_details"] == WALLET
    STATE["item_id"] = item["id"]
    doc = db.vip_batches.find_one({"id": STATE["batch_id"]})
    marker = float(doc.get(TOTAL_MARKER["added"]) or 0.0)
    assert marker >= threshold, f"cumulative alert marker not written: {marker}"
    STATE["marker_added"] = marker
    # in-app alert reached at least one staff member
    n = db.notifications.count_documents({"type": "vip_batch_threshold"})
    assert n >= 1, "no in-app vip_batch_threshold notifications created"


def test_e2e_small_add_does_not_refire():
    db = _db()
    r = requests.post(
        f"{API}/vip/batches/{STATE['batch_id']}/items", headers=_hdr(VIP_TOKEN),
        json={"items": [{"holder_name": "Pedro Chico", "amount": 20}]})
    assert r.status_code == 200, r.text
    doc = db.vip_batches.find_one({"id": STATE["batch_id"]})
    assert float(doc.get(TOTAL_MARKER["added"]) or 0.0) == STATE["marker_added"]


def test_e2e_approve_big_item_marks_approved_alert():
    db = _db()
    threshold = _threshold(db)
    r = requests.post(
        f"{API}/admin/vip-batches/items/{STATE['item_id']}/approve",
        headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    doc = db.vip_batches.find_one({"id": STATE["batch_id"]})
    marker = float(doc.get(TOTAL_MARKER["approved"]) or 0.0)
    assert marker >= threshold, f"approved-stage marker not written: {marker}"
