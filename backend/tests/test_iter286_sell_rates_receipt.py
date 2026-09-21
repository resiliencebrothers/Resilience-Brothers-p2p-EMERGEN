"""iter286 — Tasas de VENTA para conversiones + Recibo PDF de retiro.

1. Tasas de venta separadas de las de compra: cuando un cliente convierte su
   saldo por la ruta inversa (adquiere el `from_code` de la fila, ej.
   USD→USDT vía la fila USDT→USD), se aplica `rate_sell_vip` /
   `rate_sell_normal`. Sin tasa de venta → comportamiento histórico.
   Aplica al convertidor (/vip/convert) y al barrido de saldos pequeños
   (/vip/dust + /vip/convert-dust). Los campos crudos se ocultan a clientes
   (solo viaja `rate_convert_sell` pre-calculado por rol).
2. Recibo PDF firmable para retiros de empresa PAGADOS
   (GET /admin/company-withdrawals/{id}/receipt.pdf).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp,
)

API = f"{BASE_URL}/api"
MARK = "ITER286"
XC = "X86"  # moneda sintética de prueba (solo existe como fila de tasa)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _plant_rate(sell_vip=110.0, sell_normal=120.0, code=XC):
    db = _db()
    doc = {
        "id": f"rate_{MARK}_{uuid.uuid4().hex[:8]}",
        "from_code": "USDT", "to_code": code,
        "rate_normal": 100.0, "rate_vip": 100.0,
        "real_rate": None,
        "rate_sell_vip": sell_vip, "rate_sell_normal": sell_normal,
        "updated_at": _iso(),
    }
    db.rates.insert_one({k: v for k, v in doc.items()})
    return doc


def _cleanup_rates():
    _db().rates.delete_many({"id": {"$regex": f"^rate_{MARK}"}})


class _BalanceSnapshot:
    """Guarda y restaura vip_balances de los usuarios de prueba."""

    def setup_method(self, _):
        _cleanup_rates()
        db = _db()
        self._prev = {}
        for uid in ("user_test_vip01", "user_test_normal01"):
            u = db.users.find_one({"user_id": uid}, {"vip_balances": 1}) or {}
            self._prev[uid] = dict(u.get("vip_balances") or {})

    def teardown_method(self, _):
        _cleanup_rates()
        db = _db()
        for uid, bal in self._prev.items():
            db.users.update_one({"user_id": uid},
                                {"$set": {"vip_balances": bal}})


class TestSellRateConversions(_BalanceSnapshot):
    def test_vip_convert_inverse_uses_sell_rate(self):
        _plant_rate(sell_vip=110.0, sell_normal=120.0)
        _db().users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": {XC: 500.0, "USDT": 10.0}}})
        r = requests.post(f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
                          json={"from_code": XC, "to_code": "USDT",
                                "amount_from": 500})
        assert r.status_code == 200, r.text
        body = r.json()
        # venta VIP 110 → 500 / 110 = 4.5455 (antes: 500/100 = 5.0 sin margen)
        assert abs(body["amount_to"] - round(500 / 110.0, 4)) < 0.001, body
        assert abs(body["rate"] - (1 / 110.0)) < 1e-9

    def test_normal_convert_inverse_uses_normal_sell_rate(self):
        _plant_rate(sell_vip=110.0, sell_normal=120.0)
        _db().users.update_one(
            {"user_id": "user_test_normal01"},
            {"$set": {"vip_balances": {XC: 500.0, "USDT": 10.0}}})
        r = requests.post(f"{API}/vip/convert", headers=_hdr(NORMAL_TOKEN),
                          json={"from_code": XC, "to_code": "USDT",
                                "amount_from": 500})
        assert r.status_code == 200, r.text
        assert abs(r.json()["amount_to"] - round(500 / 120.0, 4)) < 0.001

    def test_convert_without_sell_rate_keeps_legacy_behavior(self):
        _plant_rate(sell_vip=None, sell_normal=None, code="X87")
        _db().users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": {"X87": 500.0, "USDT": 10.0}}})
        r = requests.post(f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
                          json={"from_code": "X87", "to_code": "USDT",
                                "amount_from": 500})
        assert r.status_code == 200, r.text
        # fallback: 1/rate_vip = 500/100 = 5.0 (comportamiento histórico)
        assert abs(r.json()["amount_to"] - 5.0) < 0.001

    def test_dust_preview_and_sweep_use_sell_rate(self):
        _plant_rate(sell_vip=110.0, sell_normal=120.0)
        db = _db()
        db.users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": {XC: 100.0, "USDT": 10.0}}})
        # preview: 100 / 110 = 0.9091 (< 5 USDT → es dust)
        rp = requests.get(f"{API}/vip/dust", headers=_hdr(VIP_TOKEN))
        assert rp.status_code == 200, rp.text
        item = next((i for i in rp.json()["items"] if i["currency"] == XC), None)
        assert item is not None, rp.json()
        assert abs(item["usdt_equivalent"] - round(100 / 110.0, 4)) < 0.001
        # sweep real acredita lo mismo
        rs = requests.post(f"{API}/vip/convert-dust", headers=_hdr(VIP_TOKEN))
        assert rs.status_code == 200, rs.text
        swept = next((i for i in rs.json()["items"] if i["currency"] == XC), None)
        assert swept is not None
        assert abs(rs.json()["credited_usdt"] - round(100 / 110.0, 4)) < 0.001
        u = db.users.find_one({"user_id": "user_test_vip01"}, {"vip_balances": 1})
        expected = 10.0 - 0.01 + round(100 / 110.0, 4)
        assert abs(float(u["vip_balances"]["USDT"]) - expected) < 0.001
        assert float(u["vip_balances"].get(XC, 0.0)) == 0.0

    def test_rates_endpoint_scrubs_raw_sell_fields_for_clients(self):
        planted = _plant_rate(sell_vip=110.0, sell_normal=120.0)
        rn = requests.get(f"{API}/rates", headers=_hdr(NORMAL_TOKEN))
        assert rn.status_code == 200
        row = next((x for x in rn.json() if x.get("id") == planted["id"]), None)
        assert row is not None
        assert "rate_sell_vip" not in row and "rate_sell_normal" not in row
        assert "real_rate" not in row
        assert abs(row["rate_convert_sell"] - 120.0) < 1e-9
        rv = requests.get(f"{API}/rates", headers=_hdr(VIP_TOKEN))
        rowv = next((x for x in rv.json() if x.get("id") == planted["id"]), None)
        assert abs(rowv["rate_convert_sell"] - 110.0) < 1e-9
        ra = requests.get(f"{API}/rates", headers=_hdr(ADMIN_TOKEN))
        rowa = next((x for x in ra.json() if x.get("id") == planted["id"]), None)
        assert rowa["rate_sell_vip"] == 110.0
        assert rowa["rate_sell_normal"] == 120.0

    def test_admin_persists_sell_rates_via_api(self):
        planted = _plant_rate(sell_vip=None, sell_normal=None)
        r = requests.put(
            f"{API}/admin/rates/{planted['id']}", headers=_hdr(ADMIN_TOKEN),
            json={"from_code": "USDT", "to_code": XC,
                  "rate_normal": 100.0, "rate_vip": 100.0,
                  "rate_sell_vip": 111.5, "rate_sell_normal": 121.5,
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        fresh = r.json()
        assert fresh["rate_sell_vip"] == 111.5
        assert fresh["rate_sell_normal"] == 121.5


# ============================================================
# Recibo PDF de retiro de empresa
# ============================================================

def _cleanup_cw():
    db = _db()
    acc_ids = [a["id"] for a in db.fund_accounts.find(
        {"name": {"$regex": MARK}}, {"id": 1})]
    db.fund_accounts.delete_many({"id": {"$in": acc_ids}})
    db.fund_account_denoms.delete_many({"account_id": {"$in": acc_ids}})
    db.company_fund_adjustments.delete_many({"source_name": {"$regex": MARK}})
    db.company_withdrawals.delete_many({"beneficiary": {"$regex": MARK}})


def _seed_paid_withdrawal():
    """Cuenta de caja CUP con fondos → retiro pagado en 1 paso (iter285)."""
    r = requests.post(f"{API}/admin/company-funds/accounts",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"name": f"{MARK} caja", "currency": "CUP",
                            "method": "cash"})
    assert r.status_code == 200, r.text
    acc = r.json()
    rf = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    row = next((f for f in rf.json() if f["currency"] == "CUP"), None)
    avail = float(row["balance_available"]) if row else 0.0
    bills = (max(0, int((-avail) // 1000) + 1) if avail < 0 else 0) + 100
    _db().company_fund_adjustments.insert_one({
        "id": str(uuid.uuid4()), "adjustment_type": "inflow",
        "currency": "CUP", "amount": float(bills * 1000), "method": "cash",
        "source_name": f"{MARK} aporte", "source_account": "", "note": MARK,
        "account_id": acc["id"], "account_label": acc["name"],
        "denominations": {"1000": bills},
        "actor_id": "admin", "actor_email": "", "actor_name": "Admin",
        "created_at": _iso(10), "cash_box_movement_id": "na",
    })
    rw = requests.post(
        f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
        json={"amount": 3000, "currency": "CUP",
              "beneficiary": f"{MARK} proveedor",
              "concept": "compra insumos",
              "totp_code": make_admin_totp(),
              "pay_now": True, "paid_from_account_id": acc["id"],
              "denominations": {"1000": 3}})
    assert rw.status_code == 200, rw.text
    return rw.json()


class TestWithdrawalReceipt:
    def setup_method(self, _):
        _cleanup_cw()

    def teardown_method(self, _):
        _cleanup_cw()

    def test_receipt_pdf_for_paid_withdrawal(self):
        cw = _seed_paid_withdrawal()
        r = requests.get(
            f"{API}/admin/company-withdrawals/{cw['id']}/receipt.pdf",
            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 2000
        assert "recibo-retiro-" in r.headers.get("content-disposition", "")

    def test_receipt_rejected_for_pending_withdrawal(self):
        r = requests.post(
            f"{API}/admin/company-withdrawals", headers=_hdr(ADMIN_TOKEN),
            json={"amount": 1, "currency": "USD",
                  "beneficiary": f"{MARK} pendiente",
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        cw = r.json()
        try:
            rr = requests.get(
                f"{API}/admin/company-withdrawals/{cw['id']}/receipt.pdf",
                headers=_hdr(ADMIN_TOKEN))
            assert rr.status_code == 400, rr.text
            assert "pagados" in rr.json()["detail"].lower()
        finally:
            requests.put(
                f"{API}/admin/company-withdrawals/{cw['id']}/status",
                headers=_hdr(ADMIN_TOKEN),
                json={"status": "rejected", "totp_code": make_admin_totp()})

    def test_receipt_forbidden_for_clients(self):
        cw = _seed_paid_withdrawal()
        r = requests.get(
            f"{API}/admin/company-withdrawals/{cw['id']}/receipt.pdf",
            headers=_hdr(VIP_TOKEN))
        assert r.status_code in (401, 403), r.text
