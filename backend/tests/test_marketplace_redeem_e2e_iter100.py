# Marketplace: canonical redeem-quote + real purchase (balance debit + pending redemption)
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def vip():
    s = requests.Session()
    s.cookies.set("session_token", "test_session_vip_X")
    return s


def _usdt(s):
    r = s.get(f"{API}/vip/balances")
    assert r.status_code == 200
    return [b for b in r.json()["balances"] if b["currency"] == "USDT"][0]["amount"]


@pytest.fixture(scope="module")
def product(vip):
    prods = vip.get(f"{API}/products").json()
    for p in prods:
        avail = (p.get("stock") or 0) - (p.get("distributed") or 0)
        if avail >= 1 and p.get("price_usdt") and 1 <= p["price_usdt"] <= 150 \
                and not p.get("owner_id") and (p.get("unit") or "unidad") == "unidad":
            return p
    pytest.skip("No cheap in-stock product available")


# Quote endpoint
class TestRedeemQuote:
    def test_quote_unauth_401(self, product):
        r = requests.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 1})
        assert r.status_code == 401

    def test_quote_404(self, vip):
        r = vip.get(f"{API}/vip/redeem-quote", params={"product_id": "nope", "quantity": 1})
        assert r.status_code == 404

    def test_quote_fraction_and_zero_400(self, vip, product):
        assert vip.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 1.5}).status_code == 400
        assert vip.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 0}).status_code == 400

    def test_quote_scales_with_qty(self, vip, product):
        q1 = vip.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 1}).json()
        q2 = vip.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 2}).json()
        assert isinstance(q1["total_usdt"], (int, float))
        assert q1["quantity"] == 1.0 and q2["quantity"] == 2.0
        assert abs(q2["total_usdt"] - 2 * q1["total_usdt"]) <= 0.02


# Purchase
class TestRedeemPurchase:
    def test_wrong_expected_total_409_no_debit(self, vip, product):
        before = _usdt(vip)
        q = vip.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 1}).json()
        r = vip.post(f"{API}/vip/redeem", json={
            "product_id": product["id"], "quantity": 1,
            "expected_total_usdt": q["total_usdt"] + 5,
            "delivery_address": "TEST_ calle ficticia 1"})
        assert r.status_code == 409
        assert str(r.json()["detail"]).startswith("PRICE_CHANGED")
        assert _usdt(vip) == before

    def test_redeem_debits_quote_total_and_creates_pending(self, vip, product):
        before = _usdt(vip)
        ids0 = {h["id"] for h in vip.get(f"{API}/vip/redemptions/mine").json()}
        stock0 = vip.get(f"{API}/products/{product['id']}").json()["stock"]
        q = vip.get(f"{API}/vip/redeem-quote", params={"product_id": product["id"], "quantity": 1}).json()
        if before < q["total_usdt"]:
            pytest.skip("Insufficient USDT balance for test user")
        r = vip.post(f"{API}/vip/redeem", json={
            "product_id": product["id"], "quantity": 1,
            "expected_total_usdt": q["total_usdt"],
            "delivery_address": "TEST_ calle ficticia 1"})
        assert r.status_code == 200, r.text
        red = r.json()
        assert red["total_usd"] == q["total_usdt"]
        assert red["status"] == "pending"
        fee = float(red.get("courier_fee_usd") or 0)
        assert round(before - _usdt(vip), 2) == round(q["total_usdt"] + fee, 2)
        hist = vip.get(f"{API}/vip/redemptions/mine").json()
        new = [h for h in hist if h["id"] not in ids0]
        assert len(new) == 1 and new[0]["id"] == red["id"] and new[0]["status"] == "pending"
        assert vip.get(f"{API}/products/{product['id']}").json()["stock"] == stock0 - 1
