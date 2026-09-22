"""iter286/iter287 — Tasa de VENTA ÚNICA + Recibo PDF de retiro.

Modelo compra/venta (dueño, Sep 2026):
  • COMPRA por nivel: la empresa compra el `from_code` al cliente Normal a
    `rate_normal` y al VIP a `rate_vip` (ej. Zelle a 680 / 690 CUP).
  • VENTA única: la empresa vende el `from_code` a TODOS al mismo precio
    `rate_sell` (ej. Zelle a 712 CUP). Se aplica en la ruta INVERSA de las
    conversiones (el cliente adquiere la moneda). Sin configurar → la mayor
    tasa de compra (sin arbitraje).
Aplica al convertidor (/vip/convert) y al barrido (/vip/dust,
/vip/convert-dust). Los campos `real_rate` y legados se ocultan a clientes.

Recibo PDF firmable para retiros de empresa PAGADOS
(GET /admin/company-withdrawals/{id}/receipt.pdf). V04 — la prueba del
retiro pendiente PREPARA fondos USD suficientes (custodia incluida) antes
de crear el retiro.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp,
)
from tests.test_iter279_s01_s07 import _run

API = f"{BASE_URL}/api"
MARK = "ITER286"
XC = "X86"  # moneda sintética de prueba (solo existe como fila de tasa)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _plant_rate(sell=110.0, code=XC, normal=100.0, vip=100.0, real=None):
    db = _db()
    # FX05: el destino de conversión debe existir en el catálogo y estar
    # activo — la moneda sintética se registra junto a su fila de tasa.
    db.currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": f"Sintética {MARK}", "type": "fiat",
                  "is_active": True, "is_convertible_to": True,
                  "test_marker": MARK}},
        upsert=True)
    doc = {
        "id": f"rate_{MARK}_{uuid.uuid4().hex[:8]}",
        "from_code": "USDT", "to_code": code,
        "rate_normal": normal, "rate_vip": vip,
        "real_rate": real,
        "rate_sell": sell,
        "updated_at": _iso(),
    }
    db.rates.insert_one({k: v for k, v in doc.items()})
    return doc


def _cleanup_rates():
    db = _db()
    db.rates.delete_many({"id": {"$regex": f"^rate_{MARK}"}})
    db.currencies.delete_many({"test_marker": MARK})


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


class TestSingleSellRateConversions(_BalanceSnapshot):
    def test_vip_convert_inverse_uses_sell_rate(self):
        _plant_rate(sell=110.0)
        _db().users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": {XC: 500.0, "USDT": 10.0}}})
        r = requests.post(f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
                          json={"from_code": XC, "to_code": "USDT",
                                "amount_from": 500})
        assert r.status_code == 200, r.text
        body = r.json()
        # venta única 110 → 500 / 110 = 4.5455
        assert abs(body["amount_to"] - round(500 / 110.0, 4)) < 0.001, body
        assert abs(body["rate"] - (1 / 110.0)) < 1e-9

    def test_normal_convert_inverse_uses_same_sell_rate(self):
        """La tasa de venta es ÚNICA: el cliente normal paga el MISMO precio
        que el VIP al adquirir la moneda (712 para todos, no por nivel)."""
        _plant_rate(sell=110.0)
        _db().users.update_one(
            {"user_id": "user_test_normal01"},
            {"$set": {"vip_balances": {XC: 500.0, "USDT": 10.0}}})
        r = requests.post(f"{API}/vip/convert", headers=_hdr(NORMAL_TOKEN),
                          json={"from_code": XC, "to_code": "USDT",
                                "amount_from": 500})
        assert r.status_code == 200, r.text
        assert abs(r.json()["amount_to"] - round(500 / 110.0, 4)) < 0.001

    def test_direct_conversion_uses_tier_buy_rates(self):
        """Conversión DIRECTA = la empresa COMPRA al cliente por nivel:
        Normal → rate_normal (NO real_rate), VIP → rate_vip."""
        _plant_rate(sell=110.0, code="X89", normal=100.0, vip=103.0,
                    real=102.0)
        db = _db()
        db.users.update_one({"user_id": "user_test_normal01"},
                            {"$set": {"vip_balances": {"USDT": 10.0}}})
        rn = requests.post(f"{API}/vip/convert", headers=_hdr(NORMAL_TOKEN),
                           json={"from_code": "USDT", "to_code": "X89",
                                 "amount_from": 5})
        assert rn.status_code == 200, rn.text
        assert abs(rn.json()["amount_to"] - 500.0) < 0.001, \
            f"normal recibe 5×100 (rate_normal), no real_rate: {rn.json()}"
        db.users.update_one({"user_id": "user_test_vip01"},
                            {"$set": {"vip_balances": {"USDT": 10.0}}})
        rv = requests.post(f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
                           json={"from_code": "USDT", "to_code": "X89",
                                 "amount_from": 5})
        assert rv.status_code == 200, rv.text
        assert abs(rv.json()["amount_to"] - 515.0) < 0.001, \
            f"VIP recibe 5×103 (rate_vip): {rv.json()}"

    def test_convert_without_sell_rate_falls_back_to_max_buy(self):
        """Sin tasa de venta → la mayor tasa de compra (jamás vender por
        debajo de lo que la empresa paga): max(100, 105) = 105."""
        _plant_rate(sell=None, code="X87", normal=100.0, vip=105.0)
        _db().users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"vip_balances": {"X87": 500.0, "USDT": 10.0}}})
        r = requests.post(f"{API}/vip/convert", headers=_hdr(VIP_TOKEN),
                          json={"from_code": "X87", "to_code": "USDT",
                                "amount_from": 500})
        assert r.status_code == 200, r.text
        assert abs(r.json()["amount_to"] - round(500 / 105.0, 4)) < 0.001

    def test_dust_preview_and_sweep_use_sell_rate(self):
        _plant_rate(sell=110.0)
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

    def test_rates_endpoint_scrubs_and_exposes_single_sell(self):
        planted = _plant_rate(sell=110.0, normal=100.0, vip=103.0, real=102.0)
        rn = requests.get(f"{API}/rates", headers=_hdr(NORMAL_TOKEN))
        assert rn.status_code == 200
        row = next((x for x in rn.json() if x.get("id") == planted["id"]), None)
        assert row is not None
        assert "real_rate" not in row
        assert "rate_sell_vip" not in row and "rate_sell_normal" not in row
        assert row["rate_sell"] == 110.0
        assert abs(row["rate_convert_sell"] - 110.0) < 1e-9
        assert abs(row["rate_convert"] - 100.0) < 1e-9, \
            "normal convierte a rate_normal, no a real_rate"
        rv = requests.get(f"{API}/rates", headers=_hdr(VIP_TOKEN))
        rowv = next((x for x in rv.json() if x.get("id") == planted["id"]), None)
        assert abs(rowv["rate_convert_sell"] - 110.0) < 1e-9, \
            "misma tasa de venta para todos los niveles"
        assert abs(rowv["rate_convert"] - 103.0) < 1e-9
        ra = requests.get(f"{API}/rates", headers=_hdr(ADMIN_TOKEN))
        rowa = next((x for x in ra.json() if x.get("id") == planted["id"]), None)
        assert rowa["rate_sell"] == 110.0 and rowa["real_rate"] == 102.0

    def test_admin_persists_single_sell_rate_via_api(self):
        planted = _plant_rate(sell=None)
        r = requests.put(
            f"{API}/admin/rates/{planted['id']}", headers=_hdr(ADMIN_TOKEN),
            json={"from_code": "USDT", "to_code": XC,
                  "rate_normal": 100.0, "rate_vip": 100.0,
                  "rate_sell": 111.5,
                  "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["rate_sell"] == 111.5

    def test_migration_consolidates_legacy_split_fields(self):
        """Los legados rate_sell_normal/rate_sell_vip se consolidan en
        `rate_sell` (el mayor) y se retiran."""
        db = _db()
        rid = f"rate_{MARK}_{uuid.uuid4().hex[:8]}"
        db.rates.insert_one({
            "id": rid, "from_code": "USDT", "to_code": "X85",
            "rate_normal": 100.0, "rate_vip": 100.0,
            "rate_sell_normal": 120.0, "rate_sell_vip": 110.0,
            "updated_at": _iso()})

        def _migrate():
            async def _f():
                from db_client import db as adb
                from services.db_migrations import migrate_split_sell_rates_to_single
                return await migrate_split_sell_rates_to_single(adb)
            return _run(_f)
        _migrate()
        fresh = db.rates.find_one({"id": rid}, {"_id": 0})
        assert fresh["rate_sell"] == 120.0, fresh
        assert "rate_sell_normal" not in fresh and "rate_sell_vip" not in fresh


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


def _seed_usd_available(margin=50.0):
    """V04 — financiación sintética suficiente para un retiro USD pendiente:
    cubre custodia de clientes y reservas de retiros ya pendientes."""
    db = _db()
    rf = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    row = next((f for f in rf.json() if f["currency"] == "USD"), None)
    avail = float(row["balance_available"]) if row else 0.0
    reserved = sum(float(w.get("amount") or 0) for w in db.company_withdrawals.find(
        {"currency": "USD", "status": {"$in": ["pending", "approved"]}},
        {"amount": 1}))
    need = round(max(0.0, -(avail - reserved)) + margin, 2)
    db.company_fund_adjustments.insert_one({
        "id": str(uuid.uuid4()), "adjustment_type": "inflow",
        "currency": "USD", "amount": need, "method": "transfer",
        "source_name": f"{MARK} aporte USD", "source_account": "",
        "note": MARK, "account_id": "", "account_label": "",
        "denominations": None, "actor_id": "admin", "actor_email": "",
        "actor_name": "Admin", "created_at": _iso(10),
    })


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
        _seed_usd_available()
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
