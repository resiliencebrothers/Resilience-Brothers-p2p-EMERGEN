"""iter293 — Revisión de mensajería 6cc9ee5: N01–N06.

N01 · La tarifa NO puede cambiar entre el inicio del pago (claim de
payout_credited) y el sello 'confirmed'; los informes usan los importes
CONGELADOS al pagar; un cambio posterior queda como ajuste pendiente único.
N02 · Revisión monotónica de tarifa: una sincronización atrasada (rev vieja)
jamás pisa la tarifa que una más nueva ya escribió (30 no retrocede a 20).
N03 · El rechazo de un depósito persiste la intención de cancelar la
recogida en el MISMO claim; el healer la completa; los avances del mensajero
re-verifican el origen; recogida ya ejecutada → incidencia visible.
N04 · La intención de registrar el efectivo viaja EN el update que sella el
'delivered'; el healer repone el evento con el mismo op_key (idempotente);
reconciliación para entregas realizadas sin evento.
N05 · Reservas dirigidas sin tope (51 de 51) y resumen diario por
agregación completa (2.001 de 2.001).
N06 · (frontend — DeliveryChatDialog) cubierto por guardas de id+generación.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
MARK = "IT293"
COURIER_A = "it293_courier_a"
CLIENT_ID = "it293_client"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _future_cutoff():
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        _motor_client._io_loop = None
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _mk_user(uid, is_courier=False):
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it293.test", "name": f"{MARK} {uid}",
        "role": "vip", "account_status": "active", "is_verified": True,
        "is_courier": is_courier, "vip_balances": {}}}, upsert=True)


def _fake_user(uid):
    return {"user_id": uid, "name": f"{MARK} {uid}", "role": "vip",
            "is_courier": True, "account_status": "active",
            "email": f"{uid}@it293.test"}


def _plant_delivery(status="available", courier_id=None, kind="redemption",
                    ref_id=None, fee=10.0, assigned_to=None, extra=None):
    did = f"it293_d_{uuid.uuid4().hex[:10]}"
    rid = ref_id or f"it293_ref_{uuid.uuid4().hex[:10]}"
    now = _iso()
    doc = {
        "id": did, "kind": kind, "ref_id": rid,
        "active_key": f"{kind}:{rid}",
        "user_id": CLIENT_ID, "client_name": f"{MARK} client",
        "address": f"{MARK} address", "province": None,
        "amount_label": f"{MARK} shipment",
        "delivery_latitude": None, "delivery_longitude": None,
        "km": 20.0, "fee_usdt": float(fee), "share_pct_snapshot": 80.0,
        "courier_share_usdt": round(fee * 0.8, 2),
        "platform_share_usdt": round(fee * 0.2, 2),
        "status": status, "courier_id": courier_id,
        "courier_name": f"{MARK} courier" if courier_id else None,
        "assigned_to_courier_id": assigned_to,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None, "created_at": now, "updated_at": now,
        "timeline": [{"status": "available", "at": now, "by": None}],
    }
    if status == "cancelled":
        doc.pop("active_key")
    doc.update(extra or {})
    _db().deliveries.insert_one(doc)
    return did, rid


def _plant_redemption(rid, status="pending", fee=10.0, rev=0):
    _db().redemptions.update_one({"id": rid}, {"$set": {
        "id": rid, "user_id": CLIENT_ID, "user_name": f"{MARK} client",
        "status": status, "total_usd": 40, "settlement_currency": "USDT",
        "courier_fee_usdt": float(fee), "courier_fee_usd": float(fee),
        "courier_fee_rev": int(rev),
        "courier_km": 20, "product_name": f"{MARK} product", "quantity": 1,
        "delivery_address": f"{MARK} address"}}, upsert=True)


def _plant_deposit(dep_id=None, status="pending", amount=1500.0,
                   currency="USD", extra=None):
    dep_id = dep_id or f"it293_dep_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": dep_id, "user_id": CLIENT_ID, "user_name": f"{MARK} client",
        "amount": float(amount), "currency": currency, "method": "cash_courier",
        "status": status, "contact_name": f"{MARK} contact",
        "pickup_address": f"{MARK} addr", "pickup_phone": "+53 555",
        "created_at": _iso(), "updated_at": _iso(),
    }
    doc.update(extra or {})
    _db().deposits.update_one({"id": dep_id}, {"$set": doc}, upsert=True)
    return dep_id


def _cleanup():
    db = _db()
    db.deliveries.delete_many({"id": {"$regex": "^it293_"}})
    db.deliveries.delete_many({"ref_id": {"$regex": "^it293_"}})
    db.redemptions.delete_many({"id": {"$regex": "^it293_"}})
    db.withdrawals.delete_many({"id": {"$regex": "^it293_"}})
    db.deposits.delete_many({"id": {"$regex": "^it293_"}})
    db.courier_cash_events.delete_many({"courier_id": {"$regex": "^it293_"}})
    db.users.delete_many({"user_id": {"$regex": "^it293_"}})
    db.notifications.delete_many({"title": {"$regex": MARK}})


def setup_module(module):
    _cleanup()
    _mk_user(COURIER_A, is_courier=True)
    _mk_user(CLIENT_ID)


def teardown_module(module):
    _cleanup()


def _simulate_payout_claim(did, share=8.0, fee=10.0):
    """Deja la entrega EXACTAMENTE como queda entre el claim del pago y el
    sello 'confirmed' de do_confirm_delivery (la ventana auditada en N01)."""
    _db().deliveries.update_one({"id": did}, {"$set": {
        "payout_credited": True, "payout_credited_at": _iso(),
        "courier_share_paid_usdt": float(share),
        "fee_paid_usdt": float(fee),
        "platform_share_paid_usdt": round(fee - share, 2)}})


def _upsert_charge(kind, ref_doc, fee, rev):
    async def _f():
        from services.deliveries import upsert_delivery_for_charge
        return await upsert_delivery_for_charge(
            kind, ref_doc, km=20.0, fee_usdt=fee, fee_rev=rev)
    return _run(_f)


# ============================================================
# N01 — la tarifa queda congelada desde que INICIA el pago
# ============================================================

class TestN01FrozenPayout:
    def test_fee_change_during_payout_window_is_blocked(self):
        did, rid = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                   fee=10.0)
        _plant_redemption(rid, fee=10.0, rev=1)
        _simulate_payout_claim(did, share=8.0, fee=10.0)
        # La tarifa cambia a 20 (rev más nueva) DENTRO de la ventana de pago.
        _plant_redemption(rid, fee=20.0, rev=2)
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        assert d["courier_share_usdt"] == 8.0, \
            "el importe mostrado no puede divergir del pagado"
        assert d["courier_share_paid_usdt"] == 8.0
        assert d.get("fee_adjustment_pending"), \
            "la diferencia debe quedar como ajuste pendiente visible"
        assert d["fee_adjustment_pending"]["courier_share_usdt"] == 16.0
        # Reintento (dos recuperaciones): el ajuste se registra UNA sola vez.
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        conflicts = [e for e in d["timeline"]
                     if e.get("status") == "fee_conflict"]
        assert len(conflicts) == 1
        assert d["courier_share_usdt"] == 8.0

    def test_fee_annulment_during_payout_window_cannot_cancel(self):
        did, rid = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                   fee=10.0)
        _plant_redemption(rid, fee=0.0, rev=2)
        _simulate_payout_claim(did, share=8.0, fee=10.0)
        _upsert_charge("redemption", {"id": rid}, fee=0.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "delivered", \
            "una anulación no puede cancelar un trabajo con pago iniciado"
        assert d.get("fee_adjustment_pending")

    def test_reports_use_frozen_paid_amounts(self):
        # Confirmada HISTÓRICA con divergencia artificial: pagado 8, campo
        # mostrado 16 — el resumen debe sumar el CONGELADO (8).
        day = "2025-02-03"
        _plant_delivery(status="confirmed", courier_id=COURIER_A, fee=20.0,
                        extra={"payout_credited": True,
                               "courier_share_paid_usdt": 8.0,
                               "fee_paid_usdt": 10.0,
                               "platform_share_paid_usdt": 2.0,
                               "updated_at": f"{day}T12:00:00+00:00"})
        r = requests.get(f"{API}/admin/deliveries/summary?date={day}",
                         headers=_hdr())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["confirmed_count"] == 1
        assert body["courier_earned_usdt"] == 8.0
        assert body["total_fees_usdt"] == 10.0
        assert body["platform_earned_usdt"] == 2.0


# ============================================================
# N02 — revisión monotónica: 30 jamás retrocede a 20
# ============================================================

class TestN02MonotonicRev:
    def test_stale_sync_cannot_overwrite_newer_fee(self):
        did, rid = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                   fee=30.0, extra={"fee_rev": 3})
        _plant_redemption(rid, fee=30.0, rev=3)
        # Ejecutor ATRASADO (leyó tarifa 20, rev 2) termina después.
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        assert d["fee_usdt"] == 30.0, "la tarifa vigente debe permanecer en 30"
        assert d["courier_share_usdt"] == 24.0, "comisión al 80% de 30"
        assert not d.get("fee_adjustment_pending"), \
            "perder contra una revisión más nueva no es un conflicto"

    def test_same_rev_resync_is_idempotent(self):
        did, rid = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                   fee=30.0, extra={"fee_rev": 3})
        _plant_redemption(rid, fee=30.0, rev=3)
        async def _f():
            from services.deliveries import sync_delivery_from_doc
            await sync_delivery_from_doc("redemptions", rid)
            await sync_delivery_from_doc("redemptions", rid)
        _run(_f)
        d = _db().deliveries.find_one({"id": did})
        assert d["fee_usdt"] == 30.0 and d["fee_rev"] == 3

    def test_newer_sync_updates_and_bumps_rev(self):
        did, rid = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                   fee=20.0, extra={"fee_rev": 2})
        _plant_redemption(rid, fee=30.0, rev=3)
        async def _f():
            from services.deliveries import sync_delivery_from_doc
            await sync_delivery_from_doc("redemptions", rid)
        _run(_f)
        d = _db().deliveries.find_one({"id": did})
        assert d["fee_usdt"] == 30.0 and d["fee_rev"] == 3

    def test_fee_change_plan_increments_revision(self):
        wid = f"it293_w_{uuid.uuid4().hex[:8]}"
        _db().withdrawals.update_one({"id": wid}, {"$set": {
            "id": wid, "user_id": CLIENT_ID, "status": "pending",
            "amount_usd": 100, "currency": "USD", "method": "cash",
            "courier_fee_currency_amount": 5.0}}, upsert=True)
        async def _f():
            from services.courier_fee import apply_fee_change_plan
            doc = {"id": wid, "courier_fee_currency_amount": 5.0}
            await apply_fee_change_plan(
                "withdrawals", doc, CLIENT_ID, "USD",
                "courier_fee_currency_amount",
                {"courier_fee_currency_amount": 5.0}, delta=0.0)
        _run(_f)
        w = _db().withdrawals.find_one({"id": wid})
        assert int(w.get("courier_fee_rev") or 0) == 1, \
            "cada decisión de cobro incrementa la revisión"
        assert w.get("delivery_sync_pending"), \
            "la tarea de sincronización viaja en el mismo claim"


# ============================================================
# N03 — rechazo de depósito con cancelación durable
# ============================================================

class TestN03DurableDepositCancel:
    def test_reject_endpoint_cancels_pickup_and_clears_task(self):
        dep = _plant_deposit()
        did, _ = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)
        r = requests.post(f"{API}/admin/deposits/{dep}/reject",
                          headers=_hdr(), json={"admin_note": f"{MARK} test"})
        assert r.status_code == 200, r.text
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "cancelled"
        doc = _db().deposits.find_one({"id": dep})
        assert doc["status"] == "rejected"
        assert not doc.get("delivery_cancel_pending"), \
            "propagación exitosa limpia la tarea durable"

    def test_healer_completes_failed_cancellation(self):
        # Estado post-fallo: depósito rechazado con la tarea viva y la
        # recogida aún aceptada (la cancelación murió en vuelo).
        dep = _plant_deposit(status="rejected", extra={
            "delivery_cancel_pending": {"at": _iso(minutes_ago=10),
                                        "note": "depósito rechazado"}})
        did, _ = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)
        async def _f():
            from services.deliveries import heal_delivery_sync
            await heal_delivery_sync(_future_cutoff())
            await heal_delivery_sync(_future_cutoff())  # idempotente
        _run(_f)
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "cancelled", \
            "el healer debe completar la cancelación pendiente"
        doc = _db().deposits.find_one({"id": dep})
        assert not doc.get("delivery_cancel_pending")
        # Un avance posterior del mensajero pierde con conflicto.
        code = self._advance(did, COURIER_A, "on_the_way")
        assert code == 409

    def test_progress_rechecks_origin_even_after_acceptance(self):
        # Sin tarea durable (variante extrema): el avance re-verifica origen.
        dep = _plant_deposit(status="rejected")
        did, _ = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)
        code = self._advance(did, COURIER_A, "on_the_way")
        assert code == 409
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "cancelled", \
            "el avance con origen rechazado cancela la recogida no ejecutada"

    def test_physical_pickup_won_race_leaves_incident(self):
        dep = _plant_deposit(status="rejected", extra={
            "delivery_cancel_pending": {"at": _iso(minutes_ago=10),
                                        "note": "depósito rechazado"}})
        did, _ = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)
        async def _f():
            from services.deliveries import heal_delivery_sync
            await heal_delivery_sync(_future_cutoff())
        _run(_f)
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "delivered", \
            "el movimiento físico ejecutado no se oculta"
        assert d.get("origin_conflict"), "queda incidencia trazable visible"
        doc = _db().deposits.find_one({"id": dep})
        assert not doc.get("delivery_cancel_pending")

    @staticmethod
    def _advance(did, uid, new_status):
        async def _f():
            import routes.deliveries as dr
            orig_ru = dr.require_user

            async def fake_ru(request):
                return _fake_user(uid)

            dr.require_user = fake_ru
            try:
                try:
                    await dr.courier_update_status(did, {"status": new_status},
                                                   None)
                    return 200
                except dr.HTTPException as ex:
                    return ex.status_code
            finally:
                dr.require_user = orig_ru
        return _run(_f)


# ============================================================
# N04 — efectivo recogido con tarea durable y reconciliación
# ============================================================

class TestN04DurableCashEvents:
    def test_delivered_transition_records_collected_event(self):
        dep = _plant_deposit(amount=1500.0)
        did, _ = _plant_delivery(status="arrived", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep,
                                 extra={"delivery_pin": "1234",
                                        "pin_verified": False})
        code = self._advance_with_pin(did, COURIER_A)
        assert code == 200
        events = list(_db().courier_cash_events.find(
            {"delivery_id": did, "kind": "collected"}))
        assert len(events) == 1 and events[0]["amount"] == 1500.0
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "delivered"
        assert not d.get("cash_event_pending"), \
            "la tarea se limpia solo tras registrar el evento"

    def test_healer_recovers_failed_cash_event_exactly_once(self):
        # Estado post-fallo: entrega sellada 'delivered' con la tarea viva y
        # CERO eventos (el insert murió después de la transición).
        dep = _plant_deposit(amount=1500.0)
        did, _ = _plant_delivery(
            status="delivered", courier_id=COURIER_A, kind="deposit",
            ref_id=dep,
            extra={"cash_event_pending": {"at": _iso(minutes_ago=10),
                                          "actor_id": COURIER_A}})
        async def _f():
            from services.deliveries import heal_delivery_sync
            await heal_delivery_sync(_future_cutoff())
            await heal_delivery_sync(_future_cutoff())  # no duplica
        _run(_f)
        events = list(_db().courier_cash_events.find(
            {"delivery_id": did, "kind": "collected"}))
        assert len(events) == 1 and events[0]["amount"] == 1500.0
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("cash_event_pending")

    def test_healer_recovers_cash_withdrawal_delivery_event(self):
        wid = f"it293_w_{uuid.uuid4().hex[:8]}"
        _db().withdrawals.update_one({"id": wid}, {"$set": {
            "id": wid, "user_id": CLIENT_ID, "status": "approved",
            "amount_usd": 200.0, "currency": "USD", "method": "cash"}},
            upsert=True)
        did, _ = _plant_delivery(
            status="delivered", courier_id=COURIER_A, kind="withdrawal",
            ref_id=wid,
            extra={"cash_event_pending": {"at": _iso(minutes_ago=10),
                                          "actor_id": COURIER_A}})
        async def _f():
            from services.deliveries import heal_delivery_sync
            await heal_delivery_sync(_future_cutoff())
        _run(_f)
        events = list(_db().courier_cash_events.find(
            {"delivery_id": did, "kind": "delivered_to_recipient"}))
        assert len(events) == 1 and events[0]["amount"] == 200.0

    def test_reconciliation_backfills_missing_event(self):
        dep = _plant_deposit(amount=750.0)
        did, _ = _plant_delivery(status="confirmed", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)
        async def _f():
            from services.courier_cash import reconcile_missing_cash_events
            await reconcile_missing_cash_events()
            await reconcile_missing_cash_events()  # marcado: no re-escanea
        _run(_f)
        events = list(_db().courier_cash_events.find(
            {"delivery_id": did, "kind": "collected"}))
        assert len(events) == 1 and events[0]["amount"] == 750.0
        d = _db().deliveries.find_one({"id": did})
        assert d.get("cash_event_checked") is True

    @staticmethod
    def _advance_with_pin(did, uid):
        async def _f():
            import routes.deliveries as dr
            orig_ru = dr.require_user

            async def fake_ru(request):
                return _fake_user(uid)

            dr.require_user = fake_ru
            try:
                try:
                    await dr.courier_update_status(
                        did, {"status": "delivered", "pin": "1234"}, None)
                    return 200
                except dr.HTTPException as ex:
                    return ex.status_code
            finally:
                dr.require_user = orig_ru
        return _run(_f)


# ============================================================
# N05 — sin topes: 51 reservas y 2.001 confirmadas del día
# ============================================================

class TestN05NoTruncation:
    def test_51_directed_reservations_all_visible(self):
        for _ in range(51):
            _plant_delivery(status="available", assigned_to=COURIER_A)
        async def _f():
            import routes.deliveries as dr
            orig_ru = dr.require_user

            async def fake_ru(request):
                return _fake_user(COURIER_A)

            dr.require_user = fake_ru
            try:
                return await dr.courier_deliveries(None)
            finally:
                dr.require_user = orig_ru
        body = _run(_f)
        reserved = [d for d in body["available"] if d.get("reserved_for_me")]
        assert len(reserved) == 51, \
            f"las 51 reservas dirigidas deben aparecer (hay {len(reserved)})"

    def test_daily_summary_aggregates_2001_confirmed(self):
        day = "2025-01-15"
        rows = []
        for i in range(2001):
            rows.append({
                "id": f"it293_bulk_{i}", "kind": "redemption",
                "ref_id": f"it293_bulkref_{i}", "status": "confirmed",
                "courier_id": COURIER_A, "courier_name": f"{MARK} courier",
                "fee_usdt": 10.0, "courier_share_usdt": 8.0,
                "platform_share_usdt": 2.0, "payout_credited": True,
                "courier_share_paid_usdt": 8.0, "fee_paid_usdt": 10.0,
                "platform_share_paid_usdt": 2.0,
                "created_at": f"{day}T10:00:00+00:00",
                "updated_at": f"{day}T12:00:00+00:00", "timeline": []})
        _db().deliveries.insert_many(rows)
        try:
            r = requests.get(f"{API}/admin/deliveries/summary?date={day}",
                             headers=_hdr())
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["confirmed_count"] == 2001, \
                f"2.001 confirmadas deben contar 2.001 ({body['confirmed_count']})"
            assert body["courier_earned_usdt"] == 16008.0
            assert body["total_fees_usdt"] == 20010.0
        finally:
            _db().deliveries.delete_many({"id": {"$regex": "^it293_bulk_"}})
