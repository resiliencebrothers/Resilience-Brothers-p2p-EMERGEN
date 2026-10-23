"""Regresiones de precisión de precio y comisión (cierran los huecos del
informe de revisión, sección 8):

1. E07 — divergencia de redondeo en compras con conversión: el total canónico
   de `_compute_product_pricing` (agregado convertido una sola vez) es el que se
   cobra, y NO coincide con precio_unitario_redondeado × cantidad (la fórmula
   que disparaba PRICE_CHANGED en falso). Se verifica con 3 y 10 unidades.
2. E01 — la comisión queda CONGELADA al confirmar la compra: cambiar
   `settings.vendor_commission_pct` entre compra y entrega NO altera el neto de
   un canje con snapshot; un canje heredado sin snapshot sí usa el fallback.

Tests deterministas: controlan su propia configuración (tasa / comisión global)
y la restauran, y limpian los documentos sembrados.
"""
import uuid

import pytest

from db_client import db
from auth_utils import now_utc, iso
from services.marketplace_fx import to_usdt
from routes.orders import _compute_product_pricing
from routes.admin import _credit_vendor_for_redemption

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# E07 — redondeo en compras con conversión
# --------------------------------------------------------------------------
async def test_multiunit_conversion_total_is_canonical_not_unit_times_qty():
    prev_settings = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "store_currency_code": 1}) or {}
    prev_rate = await db.rates.find_one(
        {"from_code": "USDT", "to_code": "CUP"}, {"_id": 0})
    try:
        await db.settings.update_one(
            {"id": "global"}, {"$set": {"store_currency_code": "CUP"}}, upsert=True)
        await db.rates.update_one(
            {"from_code": "USDT", "to_code": "CUP"},
            {"$set": {"from_code": "USDT", "to_code": "CUP",
                      "rate_normal": 800.0, "rate_vip": 800.0}}, upsert=True)

        product = {"id": "QATEST_round", "price_usd": 100.0, "cost_usd": 0.0,
                   "unit": "unidad"}  # Resilience propio, precio en CUP

        for qty in (1, 3, 10):
            pr = await _compute_product_pricing(product, qty, "normal")
            canonical = pr["total"]
            aggregate = round(100.0 * qty / 800.0, 2)
            assert canonical == aggregate, (qty, canonical, aggregate)

        # En qty=3 la fórmula ANTIGUA (unitario redondeado × cantidad) divergía:
        unit_usdt = to_usdt(100.0, 800.0)            # 0.12 (round de 0.125)
        old_formula = round(unit_usdt * 3, 2)        # 0.36
        canonical_3 = (await _compute_product_pricing(product, 3, "normal"))["total"]
        assert canonical_3 == 0.38
        assert old_formula == 0.36
        assert abs(canonical_3 - old_formula) > 0.01  # habría dado 409 falso

        # Fracción en producto NATIVO USDT (owner): redondeo a 2 decimales.
        owner_prod = {"id": "QATEST_frac", "price_usd": 0.13, "cost_usd": 0.0,
                      "unit": "kg", "owner_id": "QATEST_owner"}
        pf = await _compute_product_pricing(owner_prod, 0.333, "normal")
        assert pf["total"] == round(0.13 * 0.333, 2)  # 0.04
    finally:
        if prev_rate is not None:
            await db.rates.replace_one(
                {"from_code": "USDT", "to_code": "CUP"}, prev_rate, upsert=True)
        else:
            await db.rates.delete_one({"from_code": "USDT", "to_code": "CUP"})
        await db.settings.update_one(
            {"id": "global"},
            {"$set": {"store_currency_code": prev_settings.get("store_currency_code", "")}})


# --------------------------------------------------------------------------
# E01 — comisión congelada al confirmar la compra
# --------------------------------------------------------------------------
async def _mk_owner():
    uid = f"QATEST_vowner_{uuid.uuid4().hex[:8]}"
    await db.users.update_one(
        {"user_id": uid},
        {"$set": {"user_id": uid, "email": f"{uid}@qa.test", "name": "QA Owner",
                  "role": "vendor", "vip_balances": {}}}, upsert=True)
    return uid


async def _mk_redemption(owner_id, *, with_snapshot):
    rid = f"QATEST_vred_{uuid.uuid4().hex[:8]}"
    doc = {"id": rid, "status": "delivered", "total_usd": 100.0, "quantity": 1,
           "product_name": "QA Product", "vendor_owner_id": owner_id,
           "vendor_owner_name": "QA Owner", "settlement_currency": "USDT",
           "vendor_credited_at": ""}
    if with_snapshot:
        doc.update({"vendor_commission_pct_snapshot": 1.0,
                    "vendor_commission_base_usdt": 100.0,
                    "vendor_commission_usdt": 1.0, "vendor_net_usdt": 99.0})
    await db.redemptions.insert_one(doc)
    return rid


async def test_commission_snapshot_survives_settings_change_between_purchase_and_delivery():
    prev = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "vendor_commission_pct": 1}) or {}
    owners, reds = [], []
    try:
        # Config global al ENTREGAR = 5% (distinta del 1% sellado en la compra).
        await db.settings.update_one(
            {"id": "global"}, {"$set": {"vendor_commission_pct": 5.0}}, upsert=True)

        # Canje CON snapshot 1% → neto 99 (la config 5% NO debe aplicarse).
        o1 = await _mk_owner(); owners.append(o1)
        r1 = await _mk_redemption(o1, with_snapshot=True); reds.append(r1)
        await _credit_vendor_for_redemption(
            await db.redemptions.find_one({"id": r1}, {"_id": 0}))
        a1 = await db.redemptions.find_one({"id": r1}, {"_id": 0})
        assert a1["vendor_commission_pct"] == 1.0
        assert round(a1["vendor_credit_net"], 6) == 99.0

        # Canje HEREDADO sin snapshot → fallback a la config vigente (5% → 95).
        o2 = await _mk_owner(); owners.append(o2)
        r2 = await _mk_redemption(o2, with_snapshot=False); reds.append(r2)
        await _credit_vendor_for_redemption(
            await db.redemptions.find_one({"id": r2}, {"_id": 0}))
        a2 = await db.redemptions.find_one({"id": r2}, {"_id": 0})
        assert a2["vendor_commission_pct"] == 5.0
        assert round(a2["vendor_credit_net"], 6) == 95.0

        # Idempotencia: re-acreditar no cambia el neto congelado.
        await _credit_vendor_for_redemption(
            await db.redemptions.find_one({"id": r1}, {"_id": 0}))
        a1b = await db.redemptions.find_one({"id": r1}, {"_id": 0})
        assert round(a1b["vendor_credit_net"], 6) == 99.0
    finally:
        await db.redemptions.delete_many({"id": {"$in": reds}})
        await db.users.delete_many({"user_id": {"$in": owners}})
        await db.notifications.delete_many({"recipient_user_id": {"$in": owners}})
        await db.settings.update_one(
            {"id": "global"},
            {"$set": {"vendor_commission_pct": prev.get("vendor_commission_pct", 1.0)}})
