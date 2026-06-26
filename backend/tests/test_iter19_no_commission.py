"""iter19: verify the 5% commission for normal users has been removed.
The rate differentiation (rate_normal vs rate_vip) stays untouched."""
import os
import requests
from pymongo import MongoClient

from conftest import BASE_URL


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _make_rate(from_code: str, to_code: str, rn: float, rv: float):
    cli, db = _db()
    db.rates.delete_many({"from_code": from_code, "to_code": to_code})
    db.rates.insert_one({
        "id": f"rate_{from_code}_{to_code}",
        "from_code": from_code, "to_code": to_code,
        "rate_normal": rn, "rate_vip": rv,
    })
    cli.close()


def _create_order(token: str, from_code: str, to_code: str, amount: float):
    return requests.post(
        f"{BASE_URL}/api/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "from_code": from_code, "to_code": to_code, "amount_from": amount,
            "delivery_method": "transfer",
            "delivery_details": "test details",
            "sender_name": "Test Sender",
            "proof_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAfbLI3wAAAABJRU5ErkJggg==",
        },
    )


NORMAL_TOKEN = os.environ.get("TEST_TOKEN_NORMAL", "test_session_normal_X")
VIP_TOKEN = os.environ.get("TEST_TOKEN_VIP", "test_session_vip_X")


class TestCommissionRemoved:
    def setup_method(self, _):
        _make_rate("USD", "CUP", rn=380.0, rv=395.0)

    def test_normal_user_order_has_zero_commission(self):
        r = _create_order(NORMAL_TOKEN, "USD", "CUP", 100.0)
        assert r.status_code == 200, r.text
        order = r.json()
        assert order["commission_percent"] == 0.0
        # 100 USD * 380 = 38000 CUP, no deduction
        assert order["rate_applied"] == 380.0
        assert order["amount_to"] == 38000.0

    def test_vip_user_order_still_zero_commission_and_vip_rate(self):
        r = _create_order(VIP_TOKEN, "USD", "CUP", 100.0)
        assert r.status_code == 200, r.text
        order = r.json()
        assert order["commission_percent"] == 0.0
        assert order["rate_applied"] == 395.0
        assert order["amount_to"] == 39500.0

    def test_rate_differentiation_preserved(self):
        """Admin can still distinguish pricing via rate_normal vs rate_vip."""
        rn_order = _create_order(NORMAL_TOKEN, "USD", "CUP", 50.0).json()
        vip_order = _create_order(VIP_TOKEN, "USD", "CUP", 50.0).json()
        assert rn_order["amount_to"] < vip_order["amount_to"]
        assert rn_order["rate_applied"] == 380.0
        assert vip_order["rate_applied"] == 395.0
