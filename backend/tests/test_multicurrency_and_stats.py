"""Iteration 3 tests: multi-currency vip_balances, /api/vip/balances, /api/admin/stats, currency withdrawals, redemption USD merge."""
import pytest
import requests

from conftest import make_vip_totp, make_admin_totp, BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _set_user_balances(user_id: str, vip_balance_usd=None, vip_balances=None):
    """Helper: PUT /api/admin/users/{id} to set balances explicitly."""
    body = {"totp_code": make_admin_totp()}
    if vip_balance_usd is not None:
        body["vip_balance_usd"] = vip_balance_usd
    if vip_balances is not None:
        body["vip_balances"] = vip_balances
    r = requests.put(f"{BASE_URL}/api/admin/users/{user_id}", headers=_h(ADMIN_TOKEN), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _vip_me():
    return requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()


# ===== /api/vip/balances =====
class TestVipBalancesEndpoint:
    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/vip/balances")
        assert r.status_code == 401

    def test_normal_403(self):
        r = requests.get(f"{BASE_URL}/api/vip/balances", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_admin_200(self):
        r = requests.get(f"{BASE_URL}/api/vip/balances", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        data = r.json()
        assert "balances" in data and "total_usdt" in data
        assert isinstance(data["balances"], list)
        assert isinstance(data["total_usdt"], (int, float))

    def test_vip_legacy_plus_dict_usdt_conversion(self):
        # Set explicit balances: legacy 500 USD + dict {CUP: 38000}
        me = _vip_me()
        uid = me["user_id"]
        _set_user_balances(uid, vip_balance_usd=500.0, vip_balances={"CUP": 38000.0})
        r = requests.get(f"{BASE_URL}/api/vip/balances", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        data = r.json()
        balances = {b["currency"]: b for b in data["balances"]}
        assert "USD" in balances and "CUP" in balances
        assert balances["USD"]["amount"] == 500.0
        assert balances["CUP"]["amount"] == 38000.0
        # Conversion check: 500 USD via USDT->USD=0.98 → 500/0.98 ≈ 510.20
        # 38000 CUP via USDT->CUP=378 → 38000/378 ≈ 100.53
        usd_usdt = balances["USD"]["usdt_equivalent"]
        cup_usdt = balances["CUP"]["usdt_equivalent"]
        assert usd_usdt is not None and cup_usdt is not None
        assert abs(usd_usdt - (500 / 0.98)) < 1.0
        assert abs(cup_usdt - (38000 / 378)) < 1.0
        # Total
        assert abs(data["total_usdt"] - (usd_usdt + cup_usdt)) < 0.01


# ===== /api/admin/stats =====
class TestAdminStats:
    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats")
        assert r.status_code == 401

    def test_normal_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_vip_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=_h(VIP_TOKEN))
        assert r.status_code == 403

    def test_admin_structure(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        data = r.json()
        for key in ("inflow", "outflow", "vip_holdings", "counters"):
            assert key in data, f"missing key {key}"
        for k in ("inflow", "outflow", "vip_holdings"):
            assert "items" in data[k] and "total_usdt" in data[k]
            assert isinstance(data[k]["items"], list)
            assert isinstance(data[k]["total_usdt"], (int, float))
        c = data["counters"]
        for ck in ("users_total", "users_vip", "orders_total", "orders_pending", "withdrawals_pending"):
            assert ck in c and isinstance(c[ck], int)

    def test_admin_stats_grouped_by_currency(self):
        # Create + approve a VIP accumulate order, then verify it appears in inflow/outflow grouped
        before = requests.get(f"{BASE_URL}/api/admin/stats", headers=_h(ADMIN_TOKEN)).json()
        before_in_usd = next((i["total"] for i in before["inflow"]["items"] if i["currency"] == "USD"), 0)
        before_out_cup = next((i["total"] for i in before["outflow"]["items"] if i["currency"] == "CUP"), 0)
        order_payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 25,
                         "delivery_method": "accumulate", "delivery_details": "",
                         "sender_name": "stats-test", "proof_image": ""}
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=order_payload)
        assert r.status_code == 200
        order = r.json()
        rr = requests.put(f"{BASE_URL}/api/admin/orders/{order['id']}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved"})
        assert rr.status_code == 200
        after = requests.get(f"{BASE_URL}/api/admin/stats", headers=_h(ADMIN_TOKEN)).json()
        after_in_usd = next((i["total"] for i in after["inflow"]["items"] if i["currency"] == "USD"), 0)
        after_out_cup = next((i["total"] for i in after["outflow"]["items"] if i["currency"] == "CUP"), 0)
        assert round(after_in_usd - before_in_usd, 4) == 25.0
        assert round(after_out_cup - before_out_cup, 4) == round(order["amount_to"], 4)


# ===== Currency withdrawals =====
class TestCurrencyWithdrawals:
    def test_withdraw_with_currency_cup(self):
        me = _vip_me()
        uid = me["user_id"]
        # Set CUP balance to 50000
        _set_user_balances(uid, vip_balances={"CUP": 50000.0})
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 10000, "currency": "CUP", "method": "transfer", "details": "Bank CUP", "beneficiary_name": "Test Holder", "totp_code": make_vip_totp()})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["currency"] == "CUP"
        wid = body["id"]
        me2 = _vip_me()
        cup_after = float((me2.get("vip_balances") or {}).get("CUP", 0.0))
        assert round(cup_after, 4) == 40000.0
        # Cleanup: reject withdrawal -> refund to CUP
        rr = requests.put(f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                          headers=_h(ADMIN_TOKEN),
                          json={"status": "rejected", "admin_note": "test cleanup", "totp_code": make_admin_totp()})
        assert rr.status_code == 200
        me3 = _vip_me()
        cup_refunded = float((me3.get("vip_balances") or {}).get("CUP", 0.0))
        assert round(cup_refunded, 4) == 50000.0

    def test_withdraw_insufficient_balance_400(self):
        me = _vip_me()
        uid = me["user_id"]
        _set_user_balances(uid, vip_balances={"CUP": 100.0})
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 5000, "currency": "CUP", "method": "transfer", "details": "x", "beneficiary_name": "Test Holder", "totp_code": make_vip_totp()})
        assert r.status_code == 400

    def test_legacy_withdraw_no_currency_uses_usd(self):
        me = _vip_me()
        uid = me["user_id"]
        _set_user_balances(uid, vip_balance_usd=200.0, vip_balances={})
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 50, "method": "transfer", "details": "legacy", "beneficiary_name": "Test Holder", "totp_code": make_vip_totp()})
        assert r.status_code == 200
        body = r.json()
        assert body["currency"] == "USD"
        me2 = _vip_me()
        assert round(me2["vip_balance_usd"], 4) == 150.0
        # Cleanup: reject the withdrawal so it doesn't pollute admin stats negatively
        requests.put(f"{BASE_URL}/api/admin/withdrawals/{body['id']}/status",
                     headers=_h(ADMIN_TOKEN), json={"status": "rejected", "totp_code": make_admin_totp()})

    def test_rejected_withdrawal_refunds_correct_currency(self):
        me = _vip_me()
        uid = me["user_id"]
        _set_user_balances(uid, vip_balances={"CUP": 20000.0}, vip_balance_usd=0.0)
        r = requests.post(f"{BASE_URL}/api/vip/withdraw", headers=_h(VIP_TOKEN),
                          json={"amount_usd": 8000, "currency": "CUP", "method": "transfer", "details": "x", "beneficiary_name": "Test Holder", "totp_code": make_vip_totp()})
        assert r.status_code == 200
        wid = r.json()["id"]
        cup_after = float((_vip_me().get("vip_balances") or {}).get("CUP", 0.0))
        assert round(cup_after, 4) == 12000.0
        rr = requests.put(f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "rejected", "totp_code": make_admin_totp()})
        assert rr.status_code == 200
        cup_refunded = float((_vip_me().get("vip_balances") or {}).get("CUP", 0.0))
        assert round(cup_refunded, 4) == 20000.0
        # USD must NOT be touched
        assert round(_vip_me()["vip_balance_usd"], 4) == 0.0


# ===== Redemption USD merge =====
class TestRedemptionMergedUsd:
    def test_redeem_with_only_vip_balances_usd(self):
        # Setup: VIP has only vip_balances.USD=300 and no legacy
        me = _vip_me()
        uid = me["user_id"]
        _set_user_balances(uid, vip_balance_usd=0.0, vip_balances={"USD": 300.0})
        prods = requests.get(f"{BASE_URL}/api/products").json()
        # Pick a product with price <= 200 and stock available
        candidate = next((p for p in prods if p.get("price_usd", 9999) <= 200 and p.get("stock", 0) > 0), None)
        if not candidate:
            # Create one
            pl = {"name": "TEST_iter3_prod", "description": "test", "image_url": "",
                  "price_usd": 200, "stock": 5, "category": "test", "is_active": True}
            cr = requests.post(f"{BASE_URL}/api/admin/products", headers=_h(ADMIN_TOKEN), json=pl)
            assert cr.status_code == 200
            candidate = cr.json()
        r = requests.post(f"{BASE_URL}/api/vip/redeem", headers=_h(VIP_TOKEN),
                          json={"product_id": candidate["id"], "quantity": 1, "delivery_address": "Addr"})
        assert r.status_code == 200, r.text
        me2 = _vip_me()
        # Legacy is 0, so decrement should hit vip_balances.USD: 300 - price
        remaining_dict_usd = float((me2.get("vip_balances") or {}).get("USD", 0.0))
        assert round(remaining_dict_usd, 4) == round(300.0 - candidate["price_usd"], 4)


# ===== Double-credit regression (the iter2 HIGH bug) =====
class TestDoubleApproveGuard:
    def test_double_approve_does_not_double_credit_balance(self):
        me = _vip_me()
        uid = me["user_id"]
        _set_user_balances(uid, vip_balance_usd=0.0, vip_balances={})
        payload = {"from_code": "USD", "to_code": "CUP", "amount_from": 12,
                   "delivery_method": "accumulate", "delivery_details": "",
                   "sender_name": "double", "proof_image": ""}
        r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=payload)
        assert r.status_code == 200
        order = r.json()
        oid = order["id"]
        amt_to = order["amount_to"]
        # 1st approve
        r1 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved", "totp_code": make_admin_totp()})
        assert r1.status_code == 200
        cup1 = float((_vip_me().get("vip_balances") or {}).get("CUP", 0.0))
        assert round(cup1, 4) == round(amt_to, 4)
        # 2nd approve — should NOT increment again
        r2 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved", "totp_code": make_admin_totp()})
        assert r2.status_code == 200
        cup2 = float((_vip_me().get("vip_balances") or {}).get("CUP", 0.0))
        assert round(cup2, 4) == round(amt_to, 4), f"Double-credit regression! cup1={cup1} cup2={cup2}"
