"""Backend tests for Resilience Brothers P2P platform."""
import pytest
import requests

from conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp, make_vip_totp


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ----- Public endpoints -----
class TestPublic:
    def test_root(self):
        r = requests.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_currencies(self):
        r = requests.get(f"{BASE_URL}/api/currencies")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_rates(self):
        r = requests.get(f"{BASE_URL}/api/rates")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_products(self):
        r = requests.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ----- Auth -----
class TestAuth:
    def test_me_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_me_with_bearer_admin(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.json().get("role") == "admin"

    def test_me_with_bearer_vip(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert r.json().get("role") == "vip"

    def test_admin_endpoint_rejects_normal(self):
        r = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_admin_endpoint_rejects_vip(self):
        r = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(VIP_TOKEN))
        assert r.status_code == 403


# ----- Seed -----
class TestSeed:
    def test_seed(self):
        r = requests.post(f"{BASE_URL}/api/admin/seed", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        # Verify
        cs = requests.get(f"{BASE_URL}/api/currencies").json()
        codes = {c["code"] for c in cs}
        assert {"USDT", "USD", "CUP", "BRL", "MXN"}.issubset(codes)
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        assert any(r["from_code"] == "USD" and r["to_code"] == "CUP" for r in rates)
        prods = requests.get(f"{BASE_URL}/api/products").json()
        assert len(prods) >= 4
        # VIP rate must be better than normal
        for rt in rates:
            assert rt["rate_vip"] >= rt["rate_normal"]


# ----- Currency CRUD -----
class TestCurrencyCRUD:
    def test_currency_crud(self):
        payload = {"code": "TEST_X", "name": "Test Currency", "type": "fiat", "symbol": "T",
                   "country": "TT", "is_active": True, "payment_account": ""}
        r = requests.post(f"{BASE_URL}/api/admin/currencies", headers=_h(ADMIN_TOKEN), json=payload)
        assert r.status_code == 200
        cid = r.json()["id"]
        # List
        lst = requests.get(f"{BASE_URL}/api/currencies").json()
        assert any(c["id"] == cid for c in lst)
        # Update
        payload["name"] = "Updated Test"
        r2 = requests.put(f"{BASE_URL}/api/admin/currencies/{cid}", headers=_h(ADMIN_TOKEN), json=payload)
        assert r2.status_code == 200 and r2.json()["name"] == "Updated Test"
        # Delete
        r3 = requests.delete(f"{BASE_URL}/api/admin/currencies/{cid}", headers=_h(ADMIN_TOKEN))
        assert r3.status_code == 200
        lst2 = requests.get(f"{BASE_URL}/api/currencies").json()
        assert not any(c["id"] == cid for c in lst2)

    def test_currency_normal_forbidden(self):
        r = requests.post(f"{BASE_URL}/api/admin/currencies", headers=_h(NORMAL_TOKEN),
                          json={"code": "ZZ", "name": "Z", "type": "fiat"})
        assert r.status_code == 403


# ----- Rate CRUD -----
class TestRateCRUD:
    def test_rate_create_edit(self):
        payload = {"from_code": "USD", "to_code": "TEST_PAIR", "rate_normal": 10, "rate_vip": 11}
        r = requests.post(f"{BASE_URL}/api/admin/rates", headers=_h(ADMIN_TOKEN), json=payload)
        assert r.status_code == 200
        rid = r.json()["id"]
        # Edit
        payload2 = {**payload, "rate_normal": 12, "rate_vip": 13, "totp_code": make_admin_totp()}
        r2 = requests.put(f"{BASE_URL}/api/admin/rates/{rid}", headers=_h(ADMIN_TOKEN), json=payload2)
        assert r2.status_code == 200 and r2.json()["rate_normal"] == 12
        # Cleanup
        requests.delete(f"{BASE_URL}/api/admin/rates/{rid}", headers=_h(ADMIN_TOKEN))


# ----- Orders -----
class TestOrders:
    def test_order_normal_5pct(self):
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        rate = next(r for r in rates if r["from_code"] == "USD" and r["to_code"] == "CUP")
        payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 100,
                   "delivery_method": "transfer", "delivery_details": "Bank xxx",
                   "sender_name": "John Doe", "proof_image": "data:image/png;base64,iVBORw0KGgo="}
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        expected = round(100 * rate["rate_normal"] * 0.95, 4)
        assert data["commission_percent"] == 5.0
        assert data["amount_to"] == expected
        assert data["status"] == "pending"
        assert data["sender_name"] == "John Doe"

    def test_order_vip_0pct(self):
        rates = requests.get(f"{BASE_URL}/api/rates").json()
        rate = next(r for r in rates if r["from_code"] == "USD" and r["to_code"] == "CUP")
        payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 100,
                   "delivery_method": "transfer", "delivery_details": "x",
                   "sender_name": "VIP", "proof_image": "data:image/png;base64,iVBORw0KGgo="}
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["commission_percent"] == 0.0
        assert data["amount_to"] == round(100 * rate["rate_vip"], 4)

    def test_order_vip_accumulate_approve_credits_balance(self):
        # In iter3 multi-currency: USD->CUP accumulate credits vip_balances.CUP
        me_before = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        before_cup = float((me_before.get("vip_balances") or {}).get("CUP", 0.0))
        payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 10,
                   "delivery_method": "accumulate", "delivery_details": "",
                   "sender_name": "VIP", "proof_image": ""}
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=payload)
        assert r.status_code == 200
        order = r.json()
        oid = order["id"]
        amt_to = order["amount_to"]
        r2 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved", "admin_note": "ok"})
        assert r2.status_code == 200 and r2.json()["status"] == "approved"
        me_after = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        after_cup = float((me_after.get("vip_balances") or {}).get("CUP", 0.0))
        assert round(after_cup - before_cup, 4) == round(amt_to, 4)

    def test_orders_mine_isolation(self):
        r1 = requests.get(f"{BASE_URL}/api/orders/mine", headers=_h(NORMAL_TOKEN))
        r2 = requests.get(f"{BASE_URL}/api/orders/mine", headers=_h(VIP_TOKEN))
        assert r1.status_code == 200 and r2.status_code == 200
        for o in r1.json():
            assert o["user_role"] == "normal"
        for o in r2.json():
            assert o["user_role"] == "vip"

    def test_admin_orders_all(self):
        r = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200 and len(r.json()) >= 2

    def test_order_status_invalid(self):
        # Get any order id
        orders = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN_TOKEN)).json()
        if not orders:
            pytest.skip("no orders")
        oid = orders[0]["id"]
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "bogus"})
        assert r.status_code == 400


# ----- VIP withdrawals -----
class TestWithdrawals:
    def test_normal_cannot_withdraw(self):
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(NORMAL_TOKEN),
                          json={"amount_usd": 10, "method": "transfer", "details": "x", "beneficiary_name": "Test Holder"})
        assert r.status_code == 403

    def test_vip_withdraw_then_reject_refunds(self):
        # Read merged balance (legacy vip_balance_usd + vip_balances.USD)
        def usd_balance():
            me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
            return float(me.get("vip_balance_usd") or 0.0) + float((me.get("vip_balances") or {}).get("USD", 0.0))
        bal = usd_balance()
        if bal < 5:
            pytest.skip("VIP balance too low")
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                         json={"amount_usd": 5, "method": "transfer", "details": "Bank Y",
                               "beneficiary_name": "Test Holder", "totp_code": make_vip_totp()})
        assert r.status_code == 200
        wid = r.json()["id"]
        after = usd_balance()
        assert round(bal - after, 4) == 5.0
        # Admin rejects
        r2 = requests.put(f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                         headers=_h(ADMIN_TOKEN),
                         json={"status": "rejected", "admin_note": "no", "totp_code": make_admin_totp()})
        assert r2.status_code == 200
        refunded = usd_balance()
        assert round(refunded - after, 4) == 5.0
        refunded = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()["vip_balance_usd"]
        assert round(refunded - after, 4) == 5.0


# ----- Redemptions -----
class TestRedemptions:
    def test_normal_cannot_redeem(self):
        prods = requests.get(f"{BASE_URL}/api/products").json()
        if not prods:
            pytest.skip("no products")
        r = requests.post(f"{BASE_URL}/api/vip/redeem", headers=_h(NORMAL_TOKEN),
                          json={"product_id": prods[0]["id"], "quantity": 1, "delivery_address": "x"})
        assert r.status_code == 403

    def test_vip_redeem_and_reject_refunds(self):
        # Ensure VIP has enough balance: top up via admin update
        # First find cheap product
        prods = requests.get(f"{BASE_URL}/api/products").json()
        cheap = min(prods, key=lambda p: p["price_usd"])
        # Top up VIP balance via admin
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        new_bal = cheap["price_usd"] + 100
        requests.put(f"{BASE_URL}/api/admin/users/{me['user_id']}",
                     headers=_h(ADMIN_TOKEN), json={"vip_balance_usd": new_bal, "totp_code": make_admin_totp()})
        stock_before = cheap["stock"]
        r = requests.post(f"{BASE_URL}/api/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": cheap["id"], "quantity": 1, "delivery_address": "Addr"})
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        # Stock decreased
        prods2 = requests.get(f"{BASE_URL}/api/products").json()
        cheap2 = next(p for p in prods2 if p["id"] == cheap["id"])
        assert cheap2["stock"] == stock_before - 1
        # Balance decreased
        bal2 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()["vip_balance_usd"]
        assert round(new_bal - bal2, 4) == cheap["price_usd"]
        # Reject
        r2 = requests.put(f"{BASE_URL}/api/admin/redemptions/{rid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "rejected", "admin_note": "no"})
        assert r2.status_code == 200
        prods3 = requests.get(f"{BASE_URL}/api/products").json()
        cheap3 = next(p for p in prods3 if p["id"] == cheap["id"])
        assert cheap3["stock"] == stock_before  # refunded
        bal3 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()["vip_balance_usd"]
        assert round(bal3 - bal2, 4) == cheap["price_usd"]


# ----- Products CRUD -----
class TestProductsCRUD:
    def test_product_crud(self):
        payload = {"name": "TEST_Prod", "description": "d", "image_url": "", "price_usd": 50,
                   "stock": 3, "category": "test", "is_active": True}
        r = requests.post(f"{BASE_URL}/api/admin/products", headers=_h(ADMIN_TOKEN), json=payload)
        assert r.status_code == 200
        pid = r.json()["id"]
        payload["name"] = "TEST_Prod_Updated"
        r2 = requests.put(f"{BASE_URL}/api/admin/products/{pid}", headers=_h(ADMIN_TOKEN), json=payload)
        assert r2.status_code == 200 and r2.json()["name"] == "TEST_Prod_Updated"
        r3 = requests.delete(f"{BASE_URL}/api/admin/products/{pid}", headers=_h(ADMIN_TOKEN))
        assert r3.status_code == 200


# ----- Users admin -----
class TestUsersAdmin:
    def test_list_and_update_user(self):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        users = r.json()
        normal = next(u for u in users if u["email"] == "normal.test@resilience.com")
        # Update role to vip
        r2 = requests.put(f"{BASE_URL}/api/admin/users/{normal['user_id']}",
                          headers=_h(ADMIN_TOKEN),
                          json={"role": "vip", "vip_balance_usd": 50, "totp_code": make_admin_totp()})
        assert r2.status_code == 200
        assert r2.json()["role"] == "vip"
        assert r2.json()["vip_balance_usd"] == 50
        # Revert
        requests.put(f"{BASE_URL}/api/admin/users/{normal['user_id']}",
                     headers=_h(ADMIN_TOKEN),
                     json={"role": "normal", "vip_balance_usd": 0, "totp_code": make_admin_totp()})
