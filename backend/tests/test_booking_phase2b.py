# Service Marketplace Phase 2b — partial deposits, public reviews/ratings,
# company revenue panel (earnings) and 24h appointment reminders.
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

# Portable config: conftest.py loads the repo-local .env files into os.environ
# for local runs; CI provides these as real environment variables. Never read
# absolute /app paths or index dotenv_values() directly (breaks the CI checkout).
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CRON = os.environ.get("WEBHOOK_CRON_SECRET", "")
VIP = "user_test_vip01"
EMP = "user_test_empresa_e2e"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
SEED = str(Path(__file__).resolve().parents[1] / "seed_booking_smoke.py")


def _client(token):
    s = requests.Session()
    s.cookies.set("session_token", token)
    return s


@pytest.fixture(scope="module")
def service_id():
    out = subprocess.run([sys.executable, SEED],
                         capture_output=True, text=True, check=True).stdout
    sid = [l.split()[1] for l in out.splitlines() if l.startswith("SERVICE_ID")][0]
    yield sid
    mdb.service_bookings.delete_many({"service_id": sid})
    mdb.service_reviews.delete_many({"service_id": sid})


@pytest.fixture(scope="module")
def vip():
    return _client("bk_smoke_vip")


@pytest.fixture(scope="module")
def emp():
    return _client("bk_smoke_emp")


def _bal(uid):
    u = mdb.users.find_one({"user_id": uid}) or {}
    return float((u.get("vip_balances") or {}).get("USDT") or 0)


def _d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _set_deposit(sid, dtype, dval):
    mdb.services.update_one({"id": sid},
                            {"$set": {"deposit_type": dtype, "deposit_value": dval}})


def _book(vip, sid, d, start, qty=1):
    return vip.post(f"{BASE}/api/bookings", json={
        "service_id": sid, "slot_date": d, "slot_start": start, "quantity": qty})


def _poll(bid, pred, tries=20):
    doc = None
    for _ in range(tries):
        doc = mdb.service_bookings.find_one({"id": bid}, {"_id": 0})
        if doc and pred(doc):
            return doc
        time.sleep(1)
    return doc


def _seed_booking(bid, *, status, amount, deposit, remainder, service_id,
                  start_offset_h, end_offset_h, reminded=True):
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=start_offset_h)
    end = now + timedelta(hours=end_offset_h)
    mdb.service_bookings.insert_one({
        "id": bid, "service_id": service_id, "service_title": "Corte de pelo QA",
        "company_id": EMP, "company_name": "Empresa QA Servicios",
        "customer_id": VIP, "customer_name": "VIP Test",
        "slot_date": start.date().isoformat(), "slot_start": "09:00", "slot_end": "10:00",
        "slot_start_utc": start.isoformat(), "slot_end_utc": end.isoformat(),
        "accept_deadline_utc": "", "timezone": "America/Havana",
        "pricing_type": "fixed", "unit_price_usdt": amount, "quantity": 1,
        "amount_usdt": amount, "deposit_usdt": deposit, "remainder_usdt": remainder,
        "remainder_collected": False, "company_paid_usdt": 0.0, "currency": "USDT",
        "status": status, "note": "", "reject_reason": "",
        "pay_op_id": "", "rest_op_id": "", "refund_op_id": "", "settle_op_id": "",
        "reminded_24h": reminded,
        "created_at": now.isoformat(), "updated_at": now.isoformat(), "decided_at": ""})


# --- Partial deposit: only the deposit is charged at booking time
class TestPartialDeposit:
    def test_percent_deposit_charges_only_deposit(self, vip, service_id):
        _set_deposit(service_id, "percent", 30)
        try:
            b0 = _bal(VIP)
            r = _book(vip, service_id, _d(5), "09:00", 1)  # price 10
            assert r.status_code == 200, r.text
            bk = r.json()
            assert bk["amount_usdt"] == 10 and bk["deposit_usdt"] == 3 and bk["remainder_usdt"] == 7
            assert abs(_bal(VIP) - (b0 - 3)) < 1e-6          # only deposit debited
            # cancelling refunds only what was charged (the deposit)
            assert vip.post(f"{BASE}/api/bookings/{bk['id']}/cancel").status_code == 200
            assert abs(_bal(VIP) - b0) < 1e-6
        finally:
            _set_deposit(service_id, "none", 0)

    def test_fixed_deposit_charges_fixed(self, vip, service_id):
        _set_deposit(service_id, "fixed", 4)
        try:
            b0 = _bal(VIP)
            bk = _book(vip, service_id, _d(5), "10:00", 1).json()
            assert bk["deposit_usdt"] == 4 and bk["remainder_usdt"] == 6
            assert abs(_bal(VIP) - (b0 - 4)) < 1e-6
            vip.post(f"{BASE}/api/bookings/{bk['id']}/cancel")
        finally:
            _set_deposit(service_id, "none", 0)

    def test_no_deposit_charges_full(self, vip, service_id):
        b0 = _bal(VIP)
        bk = _book(vip, service_id, _d(5), "11:00", 1).json()
        assert bk["deposit_usdt"] == 10 and bk["remainder_usdt"] == 0
        assert abs(_bal(VIP) - (b0 - 10)) < 1e-6
        vip.post(f"{BASE}/api/bookings/{bk['id']}/cancel")


# --- Settlement collects the remainder and credits the company the full amount
class TestSettlementRemainder:
    def test_remainder_collected_and_company_credited(self, service_id):
        mdb.users.update_one({"user_id": VIP}, {"$set": {"vip_balances.USDT": 5000.0}})
        v0, c0 = _bal(VIP), _bal(EMP)
        bid = "PH2B_SET_" + uuid.uuid4().hex[:6]
        _seed_booking(bid, status="accepted", amount=100, deposit=30, remainder=70,
                      service_id=service_id, start_offset_h=-3, end_offset_h=-2)
        try:
            r = requests.post(f"{BASE}/api/cron/bookings-tick",
                              headers={"Authorization": f"Bearer {CRON}"})
            assert r.status_code == 200
            doc = _poll(bid, lambda d: d["status"] == "settled")
            assert doc["status"] == "settled"
            assert doc["remainder_collected"] is True
            assert doc["company_paid_usdt"] == 100
            assert abs(_bal(VIP) - (v0 - 70)) < 1e-6    # remainder charged post-cita
            assert abs(_bal(EMP) - (c0 + 100)) < 1e-6   # company gets the full amount
        finally:
            mdb.service_bookings.delete_one({"id": bid})


# --- Reviews: gated by a completed (settled) appointment; public; denormalised
class TestReviews:
    def test_review_requires_settled_appointment(self, vip, service_id):
        r = vip.post(f"{BASE}/api/services/{service_id}/reviews",
                     json={"rating": 5, "comment": "x"})
        assert r.status_code == 403
        assert r.json()["detail"] == "Solo puedes valorar un servicio tras completar una cita."

    def test_public_list_no_auth(self, service_id):
        r = requests.get(f"{BASE}/api/services/{service_id}/reviews")
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_review_after_settled_denormalises_rating(self, vip, service_id):
        bid = "PH2B_REV_" + uuid.uuid4().hex[:6]
        _seed_booking(bid, status="settled", amount=10, deposit=10, remainder=0,
                      service_id=service_id, start_offset_h=-48, end_offset_h=-47)
        try:
            r = vip.post(f"{BASE}/api/services/{service_id}/reviews",
                         json={"rating": 5, "comment": "Excelente"})
            assert r.status_code == 200, r.text
            assert "customer_id" not in r.json()
            lst = requests.get(f"{BASE}/api/services/{service_id}/reviews").json()
            assert any(x["comment"] == "Excelente" and x["rating"] == 5 for x in lst)
            assert all("customer_id" not in x for x in lst)
            svc = mdb.services.find_one({"id": service_id})
            assert svc["rating_count"] >= 1 and svc["rating_avg"] >= 1
            cnt = svc["rating_count"]
            # re-reviewing updates the same review (no duplicate row)
            r2 = vip.post(f"{BASE}/api/services/{service_id}/reviews",
                          json={"rating": 4, "comment": "Bien"})
            assert r2.status_code == 200
            assert mdb.services.find_one({"id": service_id})["rating_count"] == cnt
        finally:
            mdb.service_bookings.delete_one({"id": bid})
            mdb.service_reviews.delete_many({"service_id": service_id, "customer_id": VIP})


# --- Company revenue panel
class TestEarnings:
    def test_unauth_401(self):
        assert requests.get(f"{BASE}/api/company/bookings/earnings").status_code == 401

    def test_customer_forbidden(self, vip):
        assert vip.get(f"{BASE}/api/company/bookings/earnings").status_code in (401, 403)

    def test_earnings_aggregation(self, emp, service_id):
        bid = "PH2B_EARN_" + uuid.uuid4().hex[:6]
        # future (>24h) accepted booking so it is "por liberar" and not reminded
        _seed_booking(bid, status="accepted", amount=200, deposit=60, remainder=140,
                      service_id=service_id, start_offset_h=24 * 9, end_offset_h=24 * 9 + 1)
        try:
            r = emp.get(f"{BASE}/api/company/bookings/earnings")
            assert r.status_code == 200
            data = r.json()
            assert {"currency", "held_pending", "upcoming_release",
                    "settled_total", "upcoming"} <= set(data)
            item = next((u for u in data["upcoming"] if u["id"] == bid), None)
            assert item and item["amount_usdt"] == 200 and item["already_collected"] == 60
            assert data["upcoming_release"] >= 200
        finally:
            mdb.service_bookings.delete_one({"id": bid})


# --- 24h reminder (in-app + email), idempotent
class TestReminder:
    def test_24h_reminder_fires_once(self, service_id):
        # Blank emails so the cron tick never attempts a real send during tests.
        origs = {uid: (mdb.users.find_one({"user_id": uid}) or {}).get("email")
                 for uid in (VIP, EMP)}
        for uid in (VIP, EMP):
            mdb.users.update_one({"user_id": uid}, {"$set": {"email": ""}})
        bid = "PH2B_REM_" + uuid.uuid4().hex[:6]
        _seed_booking(bid, status="accepted", amount=10, deposit=10, remainder=0,
                      service_id=service_id, start_offset_h=12, end_offset_h=13,
                      reminded=False)
        try:
            requests.post(f"{BASE}/api/cron/bookings-tick",
                          headers={"Authorization": f"Bearer {CRON}"})
            doc = _poll(bid, lambda d: d.get("reminded_24h") is True)
            assert doc["reminded_24h"] is True
            q = {"recipient_user_id": VIP, "type": "service_booking_reminder",
                 "data.booking_id": bid}
            assert mdb.notifications.count_documents(q) == 1
            # second tick must not re-notify (flag guards it)
            requests.post(f"{BASE}/api/cron/bookings-tick",
                          headers={"Authorization": f"Bearer {CRON}"})
            time.sleep(3)
            assert mdb.notifications.count_documents(q) == 1
        finally:
            for uid, em in origs.items():
                mdb.users.update_one({"user_id": uid}, {"$set": {"email": em}})
            mdb.service_bookings.delete_one({"id": bid})
            mdb.notifications.delete_many({"data.booking_id": bid})
