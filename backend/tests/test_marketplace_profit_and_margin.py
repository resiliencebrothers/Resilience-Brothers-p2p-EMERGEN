"""Iter7 — Tests for:
- Product.cost_usd persistence (POST/PUT/GET)
- Redemption snapshot of cost_usd at redeem time
- /api/admin/revenue marketplace section (delivered-only)
- Negative-margin alerts on order create + on rate update (endpoint stays 200,
  no error logs from the alert path)
"""
import os
import time
import subprocess
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

BACKEND_LOG = "/var/log/supervisor/backend.err.log"
ALT_LOGS = ["/var/log/supervisor/backend.out.log"]


def _h(t=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _create_product(**overrides):
    payload = {
        "name": f"TEST_Product_{int(time.time()*1000)}",
        "description": "iter7 test product",
        "image_url": "",
        "price_usd": 550.0,
        "cost_usd": 500.0,
        "stock": 10,
        "category": "test",
        "is_active": True,
    }
    payload.update(overrides)
    r = requests.post(f"{BASE_URL}/api/admin/products", headers=_h(ADMIN), json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _ensure_vip_balance(db, min_usd=2000.0):
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"vip_balance_usd": float(min_usd) + 500}},
        upsert=False,
    )


def _tail_log(n_lines=400):
    out = ""
    for p in [BACKEND_LOG, *ALT_LOGS]:
        try:
            r = subprocess.run(["tail", "-n", str(n_lines), p], capture_output=True, text=True)
            out += r.stdout
        except Exception:
            pass
    return out


# ---------- Product cost_usd persistence ----------
class TestProductCostUsd:
    def test_create_persists_cost_usd(self):
        p = _create_product(name=f"TEST_Cost_{int(time.time()*1000)}",
                            price_usd=550, cost_usd=500, stock=10)
        assert p["price_usd"] == 550
        assert p["cost_usd"] == 500
        items = requests.get(f"{BASE_URL}/api/products").json()
        item = next((x for x in items if x["id"] == p["id"]), None)
        assert item is not None
        assert item["cost_usd"] == 500

    def test_default_cost_usd_zero(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/products",
            headers=_h(ADMIN),
            json={
                "name": f"TEST_Default_{int(time.time()*1000)}",
                "description": "x", "image_url": "",
                "price_usd": 100.0, "stock": 5,
                "category": "t", "is_active": True,
            },
        )
        assert r.status_code in (200, 201), r.text
        assert r.json().get("cost_usd") == 0.0

    def test_put_updates_cost_usd(self):
        p = _create_product(name=f"TEST_PUT_{int(time.time()*1000)}", cost_usd=100)
        payload = {**p, "cost_usd": 250.0, "price_usd": 300.0}
        r = requests.put(f"{BASE_URL}/api/admin/products/{p['id']}", headers=_h(ADMIN), json=payload)
        assert r.status_code in (200, 204), r.text
        items = requests.get(f"{BASE_URL}/api/products").json()
        got = next((x for x in items if x["id"] == p["id"]), None)
        assert got is not None
        assert got["cost_usd"] == 250.0
        assert got["price_usd"] == 300.0


# ---------- Redemption snapshot ----------
class TestRedemptionSnapshot:
    def test_redemption_records_cost_snapshot(self, db):
        _ensure_vip_balance(db, min_usd=3000)
        p = _create_product(name=f"TEST_SnapCost_{int(time.time()*1000)}",
                            price_usd=550, cost_usd=500, stock=20)
        r = requests.post(
            f"{BASE_URL}/api/vip/redeem",
            headers=_h(VIP),
            json={"product_id": p["id"], "quantity": 3, "delivery_address": "test-addr"},
        )
        assert r.status_code in (200, 201), r.text
        red = r.json()
        assert red["total_usd"] == pytest.approx(1650.0)
        assert red["cost_usd"] == pytest.approx(1500.0)
        assert red["quantity"] == 3
        # Verify persistence in DB
        from_db = db.redemptions.find_one({"id": red["id"]}, {"_id": 0})
        assert from_db is not None
        assert from_db["cost_usd"] == pytest.approx(1500.0)

    def test_cost_snapshot_independent_of_later_product_edit(self, db):
        _ensure_vip_balance(db, min_usd=3000)
        p = _create_product(name=f"TEST_Indep_{int(time.time()*1000)}",
                            price_usd=200, cost_usd=120, stock=10)
        r = requests.post(
            f"{BASE_URL}/api/vip/redeem",
            headers=_h(VIP),
            json={"product_id": p["id"], "quantity": 1, "delivery_address": "x"},
        )
        assert r.status_code in (200, 201), r.text
        red = r.json()
        assert red["cost_usd"] == pytest.approx(120.0)
        # Now edit cost on the source product
        upd = {**p, "cost_usd": 5.0}
        requests.put(f"{BASE_URL}/api/admin/products/{p['id']}", headers=_h(ADMIN), json=upd)
        # snapshot in redemption unchanged
        from_db = db.redemptions.find_one({"id": red["id"]}, {"_id": 0})
        assert from_db["cost_usd"] == pytest.approx(120.0)

    def test_redemption_defaults_cost_when_product_missing_cost(self, db):
        # Insert a legacy product directly without cost_usd
        legacy_id = f"legacy_{int(time.time()*1000)}"
        db.products.insert_one({
            "id": legacy_id,
            "name": f"TEST_Legacy_{legacy_id}",
            "description": "legacy",
            "image_url": "",
            "price_usd": 100.0,
            "stock": 10,
            "category": "t",
            "is_active": True,
            # NOTE: no cost_usd key
        })
        _ensure_vip_balance(db, min_usd=500)
        r = requests.post(
            f"{BASE_URL}/api/vip/redeem",
            headers=_h(VIP),
            json={"product_id": legacy_id, "quantity": 2, "delivery_address": "x"},
        )
        assert r.status_code in (200, 201), r.text
        red = r.json()
        assert red["cost_usd"] == pytest.approx(0.0)


# ---------- /api/admin/revenue marketplace section ----------
class TestRevenueMarketplaceSection:
    def test_revenue_shape_includes_marketplace_keys(self):
        r = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("total_profit_usdt", "p2p_profit_usdt", "marketplace_profit_usdt", "marketplace"):
            assert k in body, f"missing top-level key {k}"
        mk = body["marketplace"]
        for k in ("total_revenue_usd", "total_cost_usd", "total_profit_usd", "items", "deliveries"):
            assert k in mk, f"missing marketplace.{k}"
        assert isinstance(mk["items"], list)

    def test_marketplace_profit_after_delivery(self, db):
        _ensure_vip_balance(db, min_usd=3000)
        base = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        base_mk = base["marketplace"]
        base_profit = float(base_mk["total_profit_usd"])
        base_revenue = float(base_mk["total_revenue_usd"])
        base_cost = float(base_mk["total_cost_usd"])
        base_deliveries = int(base_mk["deliveries"])

        prod_name = f"TEST_Margin_{int(time.time()*1000)}"
        p = _create_product(name=prod_name, price_usd=550, cost_usd=500, stock=10)
        rr = requests.post(
            f"{BASE_URL}/api/vip/redeem",
            headers=_h(VIP),
            json={"product_id": p["id"], "quantity": 3, "delivery_address": "test"},
        )
        assert rr.status_code in (200, 201), rr.text
        red = rr.json()
        # Mark delivered using the documented endpoint
        upd = requests.put(
            f"{BASE_URL}/api/admin/redemptions/{red['id']}/status",
            headers=_h(ADMIN),
            json={"status": "delivered"},
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["status"] == "delivered"

        after = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        mk = after["marketplace"]
        assert mk["total_profit_usd"] == pytest.approx(base_profit + 150.0, abs=0.01)
        assert mk["total_revenue_usd"] == pytest.approx(base_revenue + 1650.0, abs=0.01)
        assert mk["total_cost_usd"] == pytest.approx(base_cost + 1500.0, abs=0.01)
        assert mk["deliveries"] == base_deliveries + 1
        assert after["marketplace_profit_usdt"] == pytest.approx(mk["total_profit_usd"], abs=0.01)
        assert after["total_profit_usdt"] == pytest.approx(
            after["p2p_profit_usdt"] + after["marketplace_profit_usdt"], abs=0.01
        )
        item = next((x for x in mk["items"] if x["product"] == prod_name), None)
        assert item is not None, f"Product {prod_name} missing"
        assert item["units"] == 3
        assert item["redemptions"] == 1
        assert item["revenue_usd"] == pytest.approx(1650.0)
        assert item["cost_usd"] == pytest.approx(1500.0)
        assert item["profit_usd"] == pytest.approx(150.0)
        # 50/550 = 9.0909...%, allow 0.05 tolerance
        assert item["margin_pct"] == pytest.approx(9.09, abs=0.05)

    def test_pending_redemption_not_counted(self, db):
        _ensure_vip_balance(db, min_usd=2000)
        base = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        base_profit = float(base["marketplace"]["total_profit_usd"])
        base_deliveries = int(base["marketplace"]["deliveries"])
        p = _create_product(name=f"TEST_Pend_{int(time.time()*1000)}",
                            price_usd=300, cost_usd=200, stock=5)
        rr = requests.post(
            f"{BASE_URL}/api/vip/redeem",
            headers=_h(VIP),
            json={"product_id": p["id"], "quantity": 1, "delivery_address": "x"},
        )
        assert rr.status_code in (200, 201), rr.text
        # Status defaults to pending — not delivered. Should NOT count.
        after = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        assert after["marketplace"]["total_profit_usd"] == pytest.approx(base_profit, abs=0.01)
        assert after["marketplace"]["deliveries"] == base_deliveries


# ---------- Negative-margin alerts ----------
def _set_rate(from_code, to_code, rate_normal, rate_vip, real_rate=None):
    payload = {
        "from_code": from_code, "to_code": to_code,
        "rate_normal": rate_normal, "rate_vip": rate_vip,
        "real_rate": real_rate,
    }
    r = requests.post(f"{BASE_URL}/api/admin/rates", headers=_h(ADMIN), json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _get_rate(from_code, to_code):
    r = requests.get(f"{BASE_URL}/api/rates")
    assert r.status_code == 200
    return next((x for x in r.json() if x["from_code"] == from_code and x["to_code"] == to_code), None)


class TestNegativeMarginOrderCreate:
    def test_no_alert_when_no_real_rate(self):
        _set_rate("USD", "CUP", rate_normal=380, rate_vip=395, real_rate=None)
        log_before = _tail_log(50)
        before_errs = log_before.count("Negative margin check failed")
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL),
            json={"from_code": "USD", "to_code": "CUP", "amount_from": 100,
                  "delivery_method": "cash", "delivery_details": "t",
                  "sender_name": "t", "proof_image": ""},
        )
        assert r.status_code == 200, r.text
        time.sleep(0.5)
        log_after = _tail_log(200)
        assert log_after.count("Negative margin check failed") == before_errs, "alert path errored"

    def test_alert_when_real_rate_makes_loss(self):
        # rate_normal=380, real_rate=350
        # amount_to = 100*380*0.95 = 36100; profit_cup = 100*350 - 36100 = -1100
        _set_rate("USD", "CUP", rate_normal=380, rate_vip=395, real_rate=350)
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL),
            json={"from_code": "USD", "to_code": "CUP", "amount_from": 100,
                  "delivery_method": "cash", "delivery_details": "t",
                  "sender_name": "t", "proof_image": ""},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["amount_from"] == 100
        assert body["amount_to"] == pytest.approx(36100.0)
        time.sleep(1.0)
        log_after = _tail_log(400)
        # Notification path should not log an error
        assert "Negative margin check failed" not in log_after.split("\n")[-200:].__str__() or \
               log_after.count("Negative margin check failed") == 0, \
               "Margin check raised an exception"


class TestNegativeMarginOnRateUpdate:
    def test_rate_update_pending_losers_does_not_break(self, db):
        # Profitable baseline first
        _set_rate("USD", "CUP", rate_normal=380, rate_vip=395, real_rate=450)
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL),
            json={"from_code": "USD", "to_code": "CUP", "amount_from": 50,
                  "delivery_method": "cash", "delivery_details": "t",
                  "sender_name": "t", "proof_image": ""},
        )
        assert r.status_code == 200, r.text
        rate = _get_rate("USD", "CUP")
        assert rate is not None
        # Flip real_rate to loss-making value — should trigger scan + alert, no crash
        upd = {**rate, "real_rate": 300}
        upd.pop("id", None); upd.pop("updated_at", None)
        ru = requests.put(f"{BASE_URL}/api/admin/rates/{rate['id']}", headers=_h(ADMIN), json=upd)
        assert ru.status_code in (200, 204), ru.text
        time.sleep(0.5)
        # backend log: no exception from rate update margin scan
        log_after = _tail_log(400)
        assert "Rate update margin scan failed" not in log_after, "Scan crashed"


# ---------- Regression on order endpoint ----------
class TestOrderEndpointRobust:
    def test_order_creation_returns_200_with_alert_path(self):
        _set_rate("USD", "CUP", rate_normal=380, rate_vip=395, real_rate=350)
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL),
            json={"from_code": "USD", "to_code": "CUP", "amount_from": 25,
                  "delivery_method": "cash", "delivery_details": "z",
                  "sender_name": "z", "proof_image": ""},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body and body["status"] == "pending"
