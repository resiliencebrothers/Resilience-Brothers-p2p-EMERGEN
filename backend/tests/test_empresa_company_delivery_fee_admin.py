"""Panel admin — editar la tarifa fija de mensajería Empresa sin tocar la BD.

GET/PUT /admin/company-delivery-fee (permiso 'deliveries'). El PUT persiste en
settings.global y el GET lo refleja junto al reparto mensajero/Resilience."""
import os

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


class TestCompanyDeliveryFeeAdmin:
    def setup_method(self, _):
        s = _db().settings.find_one({"id": "global"}, {"_id": 0, "company_delivery_fee_usdt": 1}) or {}
        self._prev = s.get("company_delivery_fee_usdt", 0)

    def teardown_method(self, _):
        _db().settings.update_one({"id": "global"},
            {"$set": {"company_delivery_fee_usdt": self._prev}}, upsert=True)

    def test_get_returns_fee_and_split(self):
        r = requests.get(f"{API}/admin/company-delivery-fee", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "fee_usdt" in body
        assert "courier_share_pct" in body and "resilience_commission_pct" in body
        assert round(body["courier_share_pct"] + body["resilience_commission_pct"], 2) == 100.0

    def test_put_persists_and_get_reflects(self):
        r = requests.put(f"{API}/admin/company-delivery-fee", headers=_h(ADMIN_TOKEN),
                         json={"fee_usdt": 7.5})
        assert r.status_code == 200, r.text
        assert r.json()["fee_usdt"] == 7.5
        # persistido en settings.global (sin tocar la BD a mano)
        s = _db().settings.find_one({"id": "global"}, {"_id": 0})
        assert s["company_delivery_fee_usdt"] == 7.5
        # el GET lo refleja
        g = requests.get(f"{API}/admin/company-delivery-fee", headers=_h(ADMIN_TOKEN)).json()
        assert g["fee_usdt"] == 7.5

    def test_put_rejects_negative(self):
        r = requests.put(f"{API}/admin/company-delivery-fee", headers=_h(ADMIN_TOKEN),
                         json={"fee_usdt": -3})
        assert r.status_code == 422  # Field ge=0

    def test_non_admin_forbidden(self):
        r = requests.put(f"{API}/admin/company-delivery-fee", headers=_h(NORMAL_TOKEN),
                         json={"fee_usdt": 1})
        assert r.status_code in (401, 403)
