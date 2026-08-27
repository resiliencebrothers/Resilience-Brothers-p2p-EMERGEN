"""iter208 — Reparto de la ganancia por mensajería.

Verifica:
1. Al confirmar la entrega, el mensajero recibe SU 80% en vip_balances.USDT.
2. El endpoint /admin/revenue expone `courier_platform_usdt` con la suma
   del share que le toca a la empresa (20% por defecto) sobre TODAS las
   entregas confirmadas — esta es la "ganancia de la empresa por
   concepto de mensajería" que se pide mostrar en la sección de Ingresos.
3. La ganancia de mensajería se suma al `total_profit_usdt` global.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"
COURIER_ID = "user_test_vip01"  # user_test_vip01 tiene is_courier=true (iter199)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_delivered(fee=10.0, share_pct=80.0, courier_id=COURIER_ID):
    """Deja una entrega en estado 'delivered', lista para que el admin
    la confirme."""
    did = f"test208_{uuid.uuid4().hex[:10]}"
    courier_share = round(fee * share_pct / 100.0, 2)
    platform_share = round(fee - courier_share, 2)
    _db().deliveries.insert_one({
        "id": did, "kind": "withdrawal", "ref_id": f"ref_{did}",
        "user_id": "user_test_normal01", "client_name": "Cliente 208",
        "address": "Calle X", "province": "La Habana",
        "amount_label": "1000 CUP",
        "km": 5.0, "fee_usdt": fee,
        "share_pct_snapshot": share_pct,
        "courier_share_usdt": courier_share,
        "platform_share_usdt": platform_share,
        "status": "delivered",
        "courier_id": courier_id, "courier_name": "Mensajero 208",
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None,
        "created_at": "2026-08-14T10:00:00+00:00",
        "updated_at": "2026-08-14T10:30:00+00:00",
        "timeline": [
            {"status": "available", "at": "2026-08-14T10:00:00+00:00"},
            {"status": "delivered", "at": "2026-08-14T10:30:00+00:00"},
        ],
    })
    return did, courier_share, platform_share


def _cleanup(*dids):
    _db().deliveries.delete_many({"id": {"$in": list(dids)}})


def _get_usdt_balance(user_id):
    u = _db().users.find_one({"user_id": user_id}, {"_id": 0, "vip_balances": 1})
    return float(((u or {}).get("vip_balances") or {}).get("USDT") or 0.0)


def _get_courier_revenue():
    r = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def test_confirm_credits_courier_share_and_platform_appears_in_revenue():
    """Reparto correcto: mensajero recibe su parte + empresa refleja su
    parte en /admin/revenue.courier_platform_usdt."""
    db = _db()
    # Snapshot inicial
    balance_before = _get_usdt_balance(COURIER_ID)
    rev_before = _get_courier_revenue()
    platform_before = float(rev_before.get("courier_platform_usdt") or 0.0)
    couriers_before = float(rev_before.get("courier_couriers_usdt") or 0.0)
    total_profit_before = float(rev_before.get("total_profit_usdt") or 0.0)

    # Simula 2 entregas delivered → confirmar
    did1, cshare1, pshare1 = _seed_delivered(fee=10.0)
    did2, cshare2, pshare2 = _seed_delivered(fee=5.0)

    try:
        for did in (did1, did2):
            r = requests.post(
                f"{API}/admin/deliveries/{did}/confirm",
                headers=_hdr(ADMIN_TOKEN),
                json={"totp_code": make_admin_totp()},
            )
            assert r.status_code == 200, f"{did}: {r.status_code} {r.text}"
            body = r.json()
            assert body["status"] == "confirmed"
            assert body["payout_credited"] is True

        # 1) Al mensajero se le acreditaron AMBAS partes courier_share.
        balance_after = _get_usdt_balance(COURIER_ID)
        expected_credit = cshare1 + cshare2
        assert round(balance_after - balance_before, 2) == round(expected_credit, 2), (
            f"balance courier no cuadra: {balance_before} → {balance_after}, "
            f"esperado +{expected_credit}"
        )

        # 2) /admin/revenue muestra la parte de la empresa (platform_share)
        #    y la parte pagada al mensajero.
        rev_after = _get_courier_revenue()
        platform_after = float(rev_after.get("courier_platform_usdt") or 0.0)
        couriers_after = float(rev_after.get("courier_couriers_usdt") or 0.0)
        assert round(platform_after - platform_before, 2) == round(pshare1 + pshare2, 2)
        assert round(couriers_after - couriers_before, 2) == round(cshare1 + cshare2, 2)
        # count de entregas confirmadas debe subir en 2
        assert (rev_after.get("courier_deliveries_count") or 0) >= 2

        # 3) La ganancia por mensajería está sumada al total_profit_usdt.
        total_profit_after = float(rev_after.get("total_profit_usdt") or 0.0)
        assert total_profit_after > total_profit_before, (
            "el total_profit_usdt debería incluir la ganancia por mensajería")
    finally:
        _cleanup(did1, did2)
        # revert courier balance change so posteriores tests no vean saldos extra
        current = _get_usdt_balance(COURIER_ID)
        delta = round(current - balance_before, 4)
        if delta:
            db.users.update_one(
                {"user_id": COURIER_ID},
                {"$inc": {"vip_balances.USDT": -delta}},
            )


def test_revenue_endpoint_exposes_courier_fields():
    """El endpoint expone los 4 campos nuevos sin depender de que haya
    entregas confirmadas — para que el frontend NO se rompa al arrancar."""
    r = requests.get(f"{API}/admin/revenue", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("courier_platform_usdt", "courier_couriers_usdt",
                "courier_total_fees_usdt", "courier_deliveries_count"):
        assert key in body, f"falta {key} en /admin/revenue"
        # todos deben ser numéricos (0 si no hay confirmadas)
        assert isinstance(body[key], (int, float)), f"{key} no es número"
