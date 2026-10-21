# iter371 — Empresa offers audit fixes: E02 expired-offer pricing, 409 PRICE_CHANGED guard,
# E04 offers banner buyability, product detail endpoint, E03 edit keeps offer, E01-B commission 1%.
import os
import copy
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"
mdb = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]

PIDS = ["prod_qaE_expired", "prod_qaE_active", "prod_qaE_closing"]


def sess(tok):
    s = requests.Session()
    s.cookies.set("session_token", tok)
    return s


@pytest.fixture(scope="module", autouse=True)
def snapshot_restore():
    prods = {p["id"]: p for p in mdb.products.find({"id": {"$in": PIDS}})}
    user = mdb.users.find_one({"user_id": "user_test_normal01"})
    yield
    # cleanup redemptions + restore products/user balance exactly
    mdb.redemptions.delete_many({"product_id": {"$in": PIDS}, "user_id": "user_test_normal01"})
    for pid, p in prods.items():
        mdb.products.replace_one({"_id": p["_id"]}, p)
    mdb.users.update_one({"_id": user["_id"]}, {"$set": {
        "vip_balances": user.get("vip_balances"),
        **({"vip_balance_usd": user["vip_balance_usd"]} if "vip_balance_usd" in user else {})}})


N = sess("qa_e_n")
CO = sess("qa_e_co")
AD = sess("test_session_admin_X")


def redeem(pid, **extra):
    body = {"product_id": pid, "quantity": 1, "fulfillment": "store_pickup", "store_id": "st_qaE"}
    body.update(extra)
    return N.post(f"{API}/vip/redeem", json=body)


# --- Product detail / catalog pricing
class TestDetail:
    def test_expired_detail_normal_price(self):
        r = N.get(f"{API}/products/prod_qaE_expired")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "_id" not in d
        assert abs(d["price_usdt"] - 100) < 0.01
        assert d["on_offer"] is False

    def test_active_detail_augmented(self):
        r = N.get(f"{API}/products/prod_qaE_active")
        assert r.status_code == 200, r.text
        d = r.json()
        assert abs(d["price_usdt"] - 80) < 0.01
        assert d["on_offer"] is True
        assert abs(float(d.get("offer_original_price_usdt") or 0) - 100) < 0.01

    def test_nonexistent_404(self):
        assert N.get(f"{API}/products/prod_does_not_exist_xyz").status_code == 404

    def test_offers_list(self):
        # Re-seed inline: the scheduler healer (heal_orphan_store_shelves) moves
        # closing-store shelves back to central, which makes the product buyable.
        mdb.products.update_one({"id": "prod_qaE_closing"}, {"$set": {
            "by_store": {"st_qaE_closing": 5.0}, "distributed": 5.0, "stock": 5.0}})
        r = N.get(f"{API}/products/offers")
        assert r.status_code == 200, r.text
        data = r.json()
        items = data if isinstance(data, list) else (data.get("items") or data.get("products") or [])
        ids = [p["id"] for p in items]
        assert "prod_qaE_active" in ids
        assert "prod_qaE_closing" not in ids
        assert "prod_qaE_expired" not in ids


# --- Purchase pricing (E02) + 409 guard
class TestRedeemPricing:
    def test_stale_expected_total_409(self):
        before = mdb.users.find_one({"user_id": "user_test_normal01"})["vip_balances"]["USDT"]
        r = redeem("prod_qaE_expired", expected_total_usdt=80)
        assert r.status_code == 409, r.text
        assert r.json()["detail"].startswith("PRICE_CHANGED")
        assert mdb.redemptions.count_documents({"product_id": "prod_qaE_expired"}) == 0
        after = mdb.users.find_one({"user_id": "user_test_normal01"})["vip_balances"]["USDT"]
        assert after == before

    def test_expired_charges_normal_price(self):
        before = mdb.users.find_one({"user_id": "user_test_normal01"})["vip_balances"]["USDT"]
        r = redeem("prod_qaE_expired", expected_total_usdt=100)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        rid = d.get("id") or (d.get("redemption") or {}).get("id")
        doc = mdb.redemptions.find_one({"id": rid}) if rid else \
            mdb.redemptions.find_one({"product_id": "prod_qaE_expired"})
        assert doc is not None
        assert abs(doc["total_usd"] - 100) < 0.01, doc["total_usd"]
        after = mdb.users.find_one({"user_id": "user_test_normal01"})["vip_balances"]["USDT"]
        assert abs((before - after) - 100) < 0.01

    def test_expired_no_expected_total_charges_100(self):
        r = redeem("prod_qaE_expired")
        assert r.status_code in (200, 201), r.text
        docs = list(mdb.redemptions.find({"product_id": "prod_qaE_expired"}))
        assert all(abs(x["total_usd"] - 100) < 0.01 for x in docs)

    def test_active_charges_discounted(self):
        r = redeem("prod_qaE_active", expected_total_usdt=80)
        assert r.status_code in (200, 201), r.text
        docs = list(mdb.redemptions.find({"product_id": "prod_qaE_active"}))
        assert len(docs) == 1
        assert abs(docs[0]["total_usd"] - 80) < 0.01


# --- E03 company edit keeps offer
class TestCompanyEdit:
    def test_description_edit_keeps_offer(self):
        r = CO.put(f"{API}/company/products/prod_qaE_active",
                   json={"description": "TEST_desc nueva", "price_usd": 80})
        assert r.status_code == 200, r.text
        db_p = mdb.products.find_one({"id": "prod_qaE_active"})
        assert db_p["description"] == "TEST_desc nueva"
        assert db_p["on_offer"] is True
        assert db_p["offer_original_price"] == 100
        g = N.get(f"{API}/products/prod_qaE_active").json()
        assert g["on_offer"] is True and abs(g["price_usdt"] - 80) < 0.01

    def test_price_change_retires_offer(self):
        r = CO.put(f"{API}/company/products/prod_qaE_active", json={"price_usd": 75})
        assert r.status_code == 200, r.text
        db_p = mdb.products.find_one({"id": "prod_qaE_active"})
        assert db_p["price_usd"] == 75
        assert db_p["on_offer"] is False
        assert float(db_p.get("offer_original_price") or 0) == 0
        g = N.get(f"{API}/products/prod_qaE_active").json()
        assert g["on_offer"] is False and abs(g["price_usdt"] - 75) < 0.01


# --- E01-B commission default
class TestCommission:
    def test_admin_settings_commission_1pct(self):
        r = AD.get(f"{API}/admin/settings")
        assert r.status_code == 200, r.text
        assert float(r.json()["vendor_commission_pct"]) == 1.0
