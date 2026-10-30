# Service Marketplace Phase 2 — USDT appointment bookings (slots, escrow debit, accept/reject/cancel refunds, cron auth, next_slot)
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

# Portable config: conftest.py loads the repo-local .env files into os.environ
# for local runs; CI provides these as real environment variables. Never read
# absolute /app paths or index dotenv_values() directly (breaks the CI checkout).
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CRON_SECRET = os.environ.get("WEBHOOK_CRON_SECRET", "")
VIP = "user_test_vip01"
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


@pytest.fixture(scope="module")
def vip():
    return _client("bk_smoke_vip")


@pytest.fixture(scope="module")
def emp():
    return _client("bk_smoke_emp")


def _bal(vip):
    u = mdb.users.find_one({"user_id": VIP})
    return float((u.get("vip_balances") or {}).get("USDT") or 0)


def _d(days):
    return (date.today() + timedelta(days=days)).isoformat()


def _book(vip, sid, d, start, qty=1):
    return vip.post(f"{BASE_URL}/api/bookings", json={
        "service_id": sid, "slot_date": d, "slot_start": start, "quantity": qty})


# --- Slots
class TestSlots:
    def test_future_slots(self, vip, service_id):
        r = vip.get(f"{BASE_URL}/api/services/{service_id}/slots", params={"date": _d(5)})
        assert r.status_code == 200, r.text
        starts = [s["start"] for s in r.json()["slots"]]
        assert starts[0] == "09:00" and starts[-1] == "16:00" and len(starts) == 8

    def test_past_slots_empty(self, vip, service_id):
        r = vip.get(f"{BASE_URL}/api/services/{service_id}/slots", params={"date": _d(-3)})
        assert r.status_code == 200 and r.json()["slots"] == []

    def test_blocked_slots_empty(self, vip, service_id):
        mdb.services.update_one({"id": service_id}, {"$set": {"blocked_dates": [_d(9)]}})
        r = vip.get(f"{BASE_URL}/api/services/{service_id}/slots", params={"date": _d(9)})
        mdb.services.update_one({"id": service_id}, {"$set": {"blocked_dates": []}})
        assert r.status_code == 200 and r.json()["slots"] == []

    def test_unauth_slots(self, service_id):
        r = requests.get(f"{BASE_URL}/api/services/{service_id}/slots", params={"date": _d(5)})
        assert r.status_code == 401


# --- next_slot on list/detail
class TestNextSlot:
    def test_detail_next_slot(self, vip, service_id):
        r = vip.get(f"{BASE_URL}/api/services/{service_id}")
        assert r.status_code == 200, r.text
        ns = r.json().get("next_slot")
        assert ns and {"date", "start", "end"} <= set(ns)

    def test_list_next_slot(self, vip, service_id):
        r = vip.get(f"{BASE_URL}/api/services")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else (data.get("items") or data.get("services") or [])
        mine = [s for s in items if s.get("id") == service_id]
        assert mine, "seeded service not in list"
        assert mine[0].get("next_slot") and mine[0]["next_slot"].get("date")


# --- Booking lifecycle
class TestBookingFlow:
    def test_book_accept_reject_refund(self, vip, emp, service_id):
        b0 = _bal(vip)
        d = _d(6)
        r = _book(vip, service_id, d, "10:00", 2)
        assert r.status_code == 200, r.text
        bk = r.json()
        assert bk["status"] == "pending" and bk["amount_usdt"] == 20
        assert abs(_bal(vip) - (b0 - 20)) < 1e-6
        # slot occupied
        slots = vip.get(f"{BASE_URL}/api/services/{service_id}/slots", params={"date": d}).json()["slots"]
        assert "10:00" not in [s["start"] for s in slots]
        # double-book
        r2 = _book(vip, service_id, d, "10:00", 1)
        assert r2.status_code == 400
        assert abs(_bal(vip) - (b0 - 20)) < 1e-6
        # mine
        mine = vip.get(f"{BASE_URL}/api/bookings/mine").json()
        assert any(x["id"] == bk["id"] for x in mine)
        # company list + accept
        lst = emp.get(f"{BASE_URL}/api/company/bookings").json()
        assert any(x["id"] == bk["id"] for x in lst)
        ra = emp.post(f"{BASE_URL}/api/company/bookings/{bk['id']}/accept")
        assert ra.status_code == 200 and ra.json()["status"] == "accepted"
        # reject -> refund
        rr = emp.post(f"{BASE_URL}/api/company/bookings/{bk['id']}/reject", json={"reason": "TEST"})
        assert rr.status_code == 200 and rr.json()["status"] == "rejected"
        assert abs(_bal(vip) - b0) < 1e-6
        rr2 = emp.post(f"{BASE_URL}/api/company/bookings/{bk['id']}/reject", json={"reason": "TEST"})
        assert rr2.status_code == 400
        assert abs(_bal(vip) - b0) < 1e-6
        # slot freed
        slots = vip.get(f"{BASE_URL}/api/services/{service_id}/slots", params={"date": d}).json()["slots"]
        assert "10:00" in [s["start"] for s in slots]

    def test_cancel_pending_and_accepted(self, vip, emp, service_id):
        b0 = _bal(vip)
        p = _book(vip, service_id, _d(7), "11:00", 1).json()
        a = _book(vip, service_id, _d(7), "12:00", 3).json()
        assert abs(_bal(vip) - (b0 - 40)) < 1e-6
        emp.post(f"{BASE_URL}/api/company/bookings/{a['id']}/accept")
        for bk in (p, a):
            r = vip.post(f"{BASE_URL}/api/bookings/{bk['id']}/cancel")
            assert r.status_code == 200 and r.json()["status"] == "cancelled"
        assert abs(_bal(vip) - b0) < 1e-6
        r = vip.post(f"{BASE_URL}/api/bookings/{p['id']}/cancel")
        assert r.status_code == 400
        assert abs(_bal(vip) - b0) < 1e-6
        # accept a cancelled one -> 400
        assert emp.post(f"{BASE_URL}/api/company/bookings/{p['id']}/accept").status_code == 400

    def test_insufficient_no_orphan(self, vip, service_id):
        b0 = _bal(vip)
        qty = int(b0 // 10) + 5
        d = _d(8)
        r = _book(vip, service_id, d, "13:00", min(qty, 999) if qty <= 999 else 999)
        if qty > 999:
            pytest.skip("balance too high for max quantity")
        assert r.status_code == 400 and "insuf" in r.json().get("detail", "").lower()
        assert mdb.service_bookings.count_documents(
            {"service_id": service_id, "slot_date": d, "slot_start": "13:00"}) == 0
        assert abs(_bal(vip) - b0) < 1e-6

    def test_own_service_and_foreign_access(self, emp, vip, service_id):
        r = _book(emp, service_id, _d(6), "14:00", 1)
        assert r.status_code in (400, 403)
        # customer cannot hit company endpoints
        assert vip.get(f"{BASE_URL}/api/company/bookings").status_code in (401, 403)

    def test_invalid_slot(self, vip, service_id):
        assert _book(vip, service_id, _d(6), "08:00", 1).status_code == 400
        assert _book(vip, service_id, _d(-2), "10:00", 1).status_code == 400
        assert _book(vip, service_id, _d(6), "10:00", 0).status_code == 422


# --- Cron
class TestCron:
    def test_cron_no_auth(self):
        assert requests.post(f"{BASE_URL}/api/cron/bookings-tick").status_code == 401

    def test_cron_bad_auth(self):
        r = requests.post(f"{BASE_URL}/api/cron/bookings-tick", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_cron_ok(self):
        r = requests.post(f"{BASE_URL}/api/cron/bookings-tick",
                          headers={"Authorization": f"Bearer {CRON_SECRET}"})
        assert r.status_code == 200 and r.json().get("ok") is True
