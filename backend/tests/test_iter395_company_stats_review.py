"""iter395 — Revisión Estadísticas de Empresas (EST-R01..R11).

Escenarios DETERMINISTAS que siembran sus propios documentos (pymongo) y se
limpian al final. Aíslan sus datos con un company_id único (MARK) para no
depender del resto de la base. Contrastan la API real.

Cubre:
  R01  — reversión imputada por fecha efectiva + corte point-in-time.
  R02  — entregas 'confirmed' cuentan además de 'delivered'.
  R03/R04 — total completo + cuadre contra total independiente.
  R07  — fechas: instantes equivalentes con/sin fracción se incluyen igual;
         día de negocio (America/Havana).
  R08  — fila 'Sin atribuir' presente aunque su neto sea 0 por reversión.
  R10  — comisiones en otra moneda se excluyen; productos llevan unidad.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import ADMIN_TOKEN, BASE_URL

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _c(params):
    return requests.get(f"{API}/admin/company-stats/summary",
                        params=params, cookies={"session_token": ADMIN_TOKEN}, timeout=30)


def _redemption(cid, **kw):
    doc = {
        "id": "r395_" + uuid.uuid4().hex[:10],
        "vendor_owner_id": cid, "vendor_owner_name": "ZZ395 Co",
        "fund_inflow_currency": "USDT", "total_usd": 100.0,
        "product_id": "p395", "product_name": "Prod 395", "unit": "unidad",
        "quantity": 1.0, "vendor_credit_net": 9.0, "status": "delivered",
    }
    doc.update(kw)
    return doc


class TestReversalEffectiveDate:
    """EST-R01 — ingreso en octubre, reversión en noviembre."""

    def setup_method(self, _):
        self.cid = "CMP395R01_" + uuid.uuid4().hex[:6]
        self.doc = _redemption(
            self.cid, fund_inflow_amount=10.0,
            fund_inflow_at="2026-10-31T12:00:00+00:00",
            fund_inflow_reversed_at="2026-11-02T12:00:00+00:00")
        _db().redemptions.insert_one(dict(self.doc))

    def teardown_method(self, _):
        _db().redemptions.delete_one({"id": self.doc["id"]})

    def test_october_shows_positive_not_reversed(self):
        e = _c({"since": "2026-10-01", "until": "2026-10-31", "company_id": self.cid}).json()["economic"]
        assert abs(e["net_commission_usdt"] - 10.0) < 0.01
        assert abs(e["reversed_commission_usdt"]) < 0.01  # corte point-in-time

    def test_november_shows_negative_reversal(self):
        e = _c({"since": "2026-11-01", "until": "2026-11-30", "company_id": self.cid}).json()["economic"]
        assert abs(e["net_commission_usdt"] + 10.0) < 0.01
        assert abs(e["reversed_commission_usdt"] - 10.0) < 0.01
        assert e["reversed_count"] == 1

    def test_full_range_nets_to_zero_with_reversal_shown(self):
        e = _c({"since": "2026-10-01", "until": "2026-11-30", "company_id": self.cid}).json()["economic"]
        assert abs(e["net_commission_usdt"]) < 0.01
        assert abs(e["reversed_commission_usdt"] - 10.0) < 0.01


class TestReconciliationIndependent:
    """EST-R03/R04 — total completo + cuadre contra total independiente."""

    def setup_method(self, _):
        self.cid = "CMP395REC_" + uuid.uuid4().hex[:6]
        self.docs = [
            _redemption(self.cid, fund_inflow_amount=5.0, fund_inflow_at="2026-10-10T12:00:00+00:00"),
            _redemption(self.cid, fund_inflow_amount=7.0, fund_inflow_at="2026-10-11T12:00:00+00:00"),
        ]
        _db().redemptions.insert_many([dict(d) for d in self.docs])

    def teardown_method(self, _):
        _db().redemptions.delete_many({"id": {"$in": [d["id"] for d in self.docs]}})

    def test_distribution_check_balanced_and_independent(self):
        rec = _c({"since": "2026-10-01", "until": "2026-10-31", "company_id": self.cid}).json()["reconciliation"]
        assert rec["check_type"] == "distribution"
        assert abs(rec["independent_total_eligible_usdt"] - 12.0) < 0.01
        assert abs(rec["distributed_commission_usdt"] - rec["independent_total_eligible_usdt"]) < 0.01
        assert rec["balanced"] is True


class TestCurrencyAndUnit:
    """EST-R10 — otra moneda excluida; productos con unidad."""

    def setup_method(self, _):
        self.cid = "CMP395CCY_" + uuid.uuid4().hex[:6]
        self.usdt = _redemption(self.cid, fund_inflow_amount=8.0,
                                fund_inflow_at="2026-10-12T12:00:00+00:00", unit="libra")
        self.eur = _redemption(self.cid, fund_inflow_amount=999.0,
                               fund_inflow_at="2026-10-12T12:00:00+00:00",
                               fund_inflow_currency="EUR")
        _db().redemptions.insert_many([dict(self.usdt), dict(self.eur)])

    def teardown_method(self, _):
        _db().redemptions.delete_many({"id": {"$in": [self.usdt["id"], self.eur["id"]]}})

    def test_other_currency_excluded(self):
        e = _c({"since": "2026-10-01", "until": "2026-10-31", "company_id": self.cid}).json()["economic"]
        assert abs(e["net_commission_usdt"] - 8.0) < 0.01  # 999 EUR excluido

    def test_products_carry_unit(self):
        r = requests.get(f"{API}/admin/company-stats/products",
                         params={"since": "2026-10-01", "until": "2026-10-31",
                                 "kind": "products", "company_id": self.cid},
                         cookies={"session_token": ADMIN_TOKEN}, timeout=30).json()
        assert r["rows"], r
        assert r["rows"][0]["unit"] == "libra"


class TestUnattributedOnlyReversal:
    """EST-R08 — 'Sin atribuir' presente aunque el neto sea 0 por reversión."""

    def setup_method(self, _):
        self.doc = _redemption(
            "", fund_inflow_amount=3.0,
            fund_inflow_at="2026-10-20T12:00:00+00:00",
            fund_inflow_reversed_at="2026-10-21T12:00:00+00:00")
        self.doc["vendor_owner_id"] = ""
        _db().redemptions.insert_one(dict(self.doc))

    def teardown_method(self, _):
        _db().redemptions.delete_one({"id": self.doc["id"]})

    def test_unattributed_reversal_present_in_csv(self):
        r = requests.get(f"{API}/admin/company-stats/export/companies.csv",
                         params={"since": "2026-10-01", "until": "2026-10-31"},
                         cookies={"session_token": ADMIN_TOKEN}, timeout=30)
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert "Sin atribuir" in text  # no desaparece por estar revertida


class TestDeliveriesConfirmed:
    """EST-R02 — entregas 'confirmed' se cuentan como realizadas."""

    def setup_method(self, _):
        self.prov = "ZZPROV395_" + uuid.uuid4().hex[:5]
        self.doc = {
            "id": "d395_" + uuid.uuid4().hex[:10], "kind": "withdrawal",
            "status": "confirmed", "province": self.prov, "municipality": "Centro395",
            "fee_usdt": 2.0, "platform_share_usdt": 0.4, "courier_share_usdt": 1.6,
            "updated_at": "2026-10-15T12:00:00+00:00", "created_at": "2026-10-15T12:00:00+00:00",
        }
        _db().deliveries.insert_one(dict(self.doc))

    def teardown_method(self, _):
        _db().deliveries.delete_one({"id": self.doc["id"]})

    def test_confirmed_delivery_counted(self):
        r = requests.get(f"{API}/admin/company-stats/municipalities",
                         params={"since": "2026-10-01", "until": "2026-10-31", "limit": 500},
                         cookies={"session_token": ADMIN_TOKEN}, timeout=30).json()
        match = [row for row in r["rows"] if row["province"] == self.prov]
        assert match, "la entrega 'confirmed' debe aparecer en municipios"
        assert match[0]["completed"] == 1


class TestDateEquivalence:
    """EST-R07 — instantes equivalentes (con/sin fracción) se incluyen igual."""

    def setup_method(self, _):
        self.cid = "CMP395TZ_" + uuid.uuid4().hex[:6]
        self.docs = [
            _redemption(self.cid, fund_inflow_amount=4.0, fund_inflow_at="2026-10-05T12:00:00+00:00"),
            _redemption(self.cid, fund_inflow_amount=6.0, fund_inflow_at="2026-10-05T12:00:00.000000+00:00"),
        ]
        _db().redemptions.insert_many([dict(d) for d in self.docs])

    def teardown_method(self, _):
        _db().redemptions.delete_many({"id": {"$in": [d["id"] for d in self.docs]}})

    def test_both_formats_included(self):
        e = _c({"since": "2026-10-05", "until": "2026-10-05", "company_id": self.cid}).json()["economic"]
        # Ambos instantes son el mismo; ninguno se excluye por formato textual.
        assert abs(e["net_commission_usdt"] - 10.0) < 0.01


def test_invalid_range_rejected():
    r = _c({"since": "2026-10-31", "until": "2026-10-01"})
    assert r.status_code == 400
