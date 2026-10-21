# iter370 — Company (Empresa) offers HTTP + pickup store + purchase→delivered→1% commission (6-dec precision)
import os
import copy
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


def _load_env(path, key):
    with open(path) as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or _load_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL") or _load_env("/app/backend/.env", "MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _load_env("/app/backend/.env", "DB_NAME")

PID = "prod_qaoff"
SID = "st_qaoff"
CO = "usr_qaoff_co"
CLIENT = "user_test_normal01"

mdb = MongoClient(MONGO_URL)[DB_NAME]
CREATED_RIDS = []


def sess(token):
    s = requests.Session()
    s.cookies.set("session_token", token)
    s.headers.update({"Content-Type": "application/json"})
    return s


CO_S = sess("qa_sess_co")
NORMAL_S = sess("qa_sess_normal")
ADMIN_S = sess("test_session_admin_X")


def usdt(uid):
    u = mdb.users.find_one({"user_id": uid}, {"_id": 0, "vip_balances": 1}) or {}
    return float((u.get("vip_balances") or {}).get("USDT") or 0)


@pytest.fixture(scope="module", autouse=True)
def snapshot_restore():
    prod = copy.deepcopy(mdb.products.find_one({"id": PID}))
    co_u = copy.deepcopy(mdb.users.find_one({"user_id": CO}))
    cl_u = copy.deepcopy(mdb.users.find_one({"user_id": CLIENT}))
    # seed note: QA seed put 500 in `balances.USDT`, but the app reads `vip_balances.USDT`
    if usdt(CLIENT) < 200:
        mdb.users.update_one({"user_id": CLIENT}, {"$set": {"vip_balances.USDT": 500.0}})
    yield
    # restore seeded state + delete TEST-created artifacts
    mdb.products.replace_one({"_id": prod["_id"]}, prod)
    mdb.users.replace_one({"_id": co_u["_id"]}, co_u)
    mdb.users.replace_one({"_id": cl_u["_id"]}, cl_u)
    for rid in CREATED_RIDS:
        mdb.redemptions.delete_many({"id": rid})
        mdb.company_fund_adjustments.delete_many({"ref_id": rid})
        mdb.notifications.delete_many({"data.redemption_id": rid})
        mdb.deliveries.delete_many({"ref_id": rid})


# ---------------- Offer endpoints ----------------
class TestCompanyOffers:
    def test_a_delete_offer_restores_price(self):
        r = CO_S.delete(f"{BASE_URL}/api/company/products/{PID}/offer")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["on_offer"] is False
        assert float(d["price_usd"]) == 100
        assert "offer_original_price" not in d

    def test_a2_offers_list_excludes_after_delete(self):
        r = NORMAL_S.get(f"{BASE_URL}/api/products/offers")
        assert r.status_code == 200
        assert PID not in [p["id"] for p in r.json()]

    def test_b_post_offer_80(self):
        r = CO_S.post(f"{BASE_URL}/api/company/products/{PID}/offer", json={"discount_price": 80})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["on_offer"] is True
        assert float(d["price_usd"]) == 80
        assert float(d["offer_original_price"]) == 100
        assert float(d["offer_discount_pct"]) == 20
        db_doc = mdb.products.find_one({"id": PID})
        assert db_doc["price_usd"] == 80 and db_doc["on_offer"] is True

    def test_b2_offers_list_includes(self):
        r = NORMAL_S.get(f"{BASE_URL}/api/products/offers")
        assert r.status_code == 200
        m = [p for p in r.json() if p["id"] == PID]
        assert m, "prod_qaoff missing from offers list"
        p = m[0]
        print("offers entry:", {k: p.get(k) for k in ("price_usd", "price_usdt", "offer_original_price_usdt", "offer_discount_pct", "on_offer")})
        assert float(p["price_usdt"]) == 80
        assert float(p["offer_original_price_usdt"]) == 100
        assert float(p["offer_discount_pct"]) > 0

    def test_c_discount_not_lower_422(self):
        r = CO_S.post(f"{BASE_URL}/api/company/products/{PID}/offer", json={"discount_price": 999})
        assert r.status_code == 422, r.text

    def test_c2_discount_equal_original_422(self):
        r = CO_S.post(f"{BASE_URL}/api/company/products/{PID}/offer", json={"discount_price": 100})
        assert r.status_code == 422, r.text

    def test_d_past_end_422(self):
        r = CO_S.post(f"{BASE_URL}/api/company/products/{PID}/offer",
                      json={"discount_price": 70, "ends_at": "2020-01-01"})
        assert r.status_code == 422, r.text
        assert float(mdb.products.find_one({"id": PID})["price_usd"]) == 80  # unchanged

    def test_e_future_end_200(self):
        fut = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
        r = CO_S.post(f"{BASE_URL}/api/company/products/{PID}/offer",
                      json={"discount_price": 90, "ends_at": fut})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["offer_ends_at"].startswith(fut)
        assert float(d["price_usd"]) == 90
        assert float(d["offer_original_price"]) == 100  # no chained discount
        assert float(d["offer_discount_pct"]) == 10

    def test_f_unauth_and_other_role(self):
        r = NORMAL_S.post(f"{BASE_URL}/api/company/products/{PID}/offer", json={"discount_price": 50})
        assert r.status_code in (401, 403), r.text
        r2 = requests.post(f"{BASE_URL}/api/company/products/{PID}/offer", json={"discount_price": 50})
        assert r2.status_code in (401, 403)


# ---------------- Pickup store ----------------
class TestPickupStore:
    def test_stores_for_company_product(self):
        r = NORMAL_S.get(f"{BASE_URL}/api/stores", params={"product_id": PID})
        assert r.status_code == 200, r.text
        m = [s for s in r.json() if s["id"] == SID]
        assert m, r.text
        assert float(m[0]["available_qty"]) == 5


# ---------------- Purchase → delivered → commission ----------------
def _buy_and_deliver(expected_total):
    co_before = usdt(CO)
    cl_before = usdt(CLIENT)
    r = NORMAL_S.post(f"{BASE_URL}/api/vip/redeem",
                      json={"product_id": PID, "quantity": 1,
                            "fulfillment": "store_pickup", "store_id": SID})
    assert r.status_code == 200, r.text
    red = r.json()
    rid = red["id"]
    CREATED_RIDS.append(rid)
    print("redemption:", {k: red.get(k) for k in ("id", "status", "total_usd", "settlement_currency", "vendor_owner_id", "fulfillment")})
    assert abs(float(red["total_usd"]) - expected_total) < 1e-9
    assert abs(usdt(CLIENT) - (cl_before - expected_total)) < 1e-6
    pr = ADMIN_S.post(f"{BASE_URL}/api/admin/redemptions/{rid}/pickup-ready")
    assert pr.status_code == 200, pr.text
    assert pr.json()["status"] == "approved"
    d = ADMIN_S.put(f"{BASE_URL}/api/admin/redemptions/{rid}/status",
                    json={"status": "delivered", "admin_note": "TEST_iter370"})
    assert d.status_code == 200, d.text
    doc = mdb.redemptions.find_one({"id": rid}, {"_id": 0})
    adj = mdb.company_fund_adjustments.find_one({"dedupe_key": f"vendor-fund:{rid}:c0"}, {"_id": 0})
    co_after = usdt(CO)
    print("vendor_credit_net:", doc.get("vendor_credit_net"), "pct:", doc.get("vendor_commission_pct"),
          "fund_inflow_amount:", doc.get("fund_inflow_amount"))
    print("fund adj:", adj and {k: adj.get(k) for k in ("amount", "currency", "adjustment_type", "source_name", "dedupe_key")})
    print("company USDT before/after:", co_before, co_after)
    return rid, doc, adj, co_before, co_after


class TestCommissionFlow:
    def test_full_90_sale(self):
        p = mdb.products.find_one({"id": PID})
        assert p["price_usd"] == 90 and p.get("on_offer")
        rid, doc, adj, b, a = _buy_and_deliver(90.0)
        assert doc["status"] == "delivered"
        assert doc["vendor_commission_pct"] == 1.0
        assert doc["vendor_credit_net"] == 89.1
        assert adj is not None, "fund adjustment missing"
        assert adj["adjustment_type"] == "inflow" and adj["currency"] == "USDT"
        assert adj["amount"] == 0.9
        assert adj["source_name"] == "Marketplace Empresas"
        assert abs((a - b) - 89.1) < 1e-6
        assert abs(doc["vendor_credit_net"] + adj["amount"] - 90.0) < 1e-9
        # idempotent re-PUT delivered: no double credit
        r = ADMIN_S.put(f"{BASE_URL}/api/admin/redemptions/{rid}/status", json={"status": "delivered"})
        assert r.status_code == 200
        assert abs(usdt(CO) - a) < 1e-9
        assert mdb.company_fund_adjustments.count_documents({"ref_id": rid}) == 1

    def test_small_010_sale_subcent(self):
        r = CO_S.post(f"{BASE_URL}/api/company/products/{PID}/offer", json={"discount_price": 0.10})
        assert r.status_code == 200, r.text
        assert float(r.json()["price_usd"]) == 0.1
        rid, doc, adj, b, a = _buy_and_deliver(0.1)
        assert doc["vendor_credit_net"] == 0.099
        assert adj is not None, "fund adjustment missing for 0.10 sale"
        assert adj["amount"] == 0.001, f"sub-cent commission regression: {adj['amount']}"
        assert abs((a - b) - 0.099) < 1e-9
